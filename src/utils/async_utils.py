#   Copyright 2020-present Michael Hall
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.


from __future__ import annotations

import asyncio
import logging
import time
from typing import (
    Awaitable,
    Callable,
    Generic,
    Literal,
    Optional,
    Sequence,
    TypeVar,
    overload,
)

_T = TypeVar("_T")

__all__ = ("Waterfall",)


log = logging.getLogger("salamander.utils.async_utils")


class Waterfall(Generic[_T]):
    def __init__(
        self,
        max_wait: float,
        max_quantity: int,
        async_callback: Callable[[Sequence[_T]], Awaitable],
        *,
        max_wait_finalize: int = 3,
    ):
        asyncio.get_running_loop()
        self.queue = asyncio.Queue()  # type: asyncio.Queue[_T]
        self.max_wait: float = max_wait
        self.max_wait_finalize: int = 3
        self.max_quantity: int = max_quantity
        self.callback: Callable[[Sequence[_T]], Awaitable] = async_callback
        self.task: Optional[asyncio.Task] = None
        self._alive: bool = False

    def start(self):
        if self.task is not None:
            raise RuntimeError("Already Running")

        self._alive = True
        self.task = asyncio.create_task(self._loop())

    @overload
    def stop(self, wait: Literal[True]) -> Awaitable:
        ...

    @overload
    def stop(self, wait: Literal[False]):
        ...

    @overload
    def stop(self, wait: bool = False) -> Optional[Awaitable]:
        ...

    def stop(self, wait: bool = False):
        self._alive = False
        if wait:
            return self.queue.join()

    def put(self, item: _T):
        if not self._alive:
            raise RuntimeError("Can't put something in a non-running Waterfall.")
        self.queue.put_nowait(item)

    async def _loop(self):
        try:

            while self._alive:
                queue_items: Sequence[_T] = []
                iter_start = time.monotonic()

                while (
                    this_max_wait := (time.monotonic() - iter_start)
                ) < self.max_wait:
                    try:
                        n = await asyncio.wait_for(self.queue.get(), this_max_wait)
                    except asyncio.TimeoutError:
                        continue
                    else:
                        queue_items.append(n)
                    if len(queue_items) >= self.max_quantity:
                        break

                    if not queue_items:
                        continue

                num_items = len(queue_items)

                asyncio.create_task(self.callback(queue_items))

                for _ in range(num_items):
                    self.queue.task_done()

        except asyncio.CancelledError:
            log.debug("Recieved waterfall cancellation.")
        finally:
            f = asyncio.create_task(
                self._finalize(), name="salamander.waterfall.finalizer"
            )
            try:
                await asyncio.wait_for(f, timeout=self.max_wait_finalize)
            except asyncio.TimeoutError:
                log.info("Max wait during waterfall finalization occurred.")

    async def _finalize(self):

        # WARNING: Do not allow an async context switch before the gather below

        self._alive = False
        remaining_items: Sequence[_T] = []

        while not self.queue.empty():
            try:
                ev = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                # we should never hit this, asyncio queues know their size reliably when used appropriately.
                break

            remaining_items.append(ev)

        if not remaining_items:
            return

        num_remaining = len(remaining_items)

        pending_futures = []

        for chunk in (
            remaining_items[p : p + self.max_quantity]
            for p in range(0, num_remaining, self.max_quantity)
        ):
            fut = asyncio.create_task(
                self.callback(chunk), name="salamander.waterfall.finalizing_task"
            )
            pending_futures.append(fut)

        gathered = asyncio.create_task(
            asyncio.gather(*pending_futures),
            name="salamander.waterfall.finalizing_task",
        )

        try:
            await asyncio.wait_for(gathered, timeout=self.max_wait_finalize)
        except asyncio.TimeoutError:
            for task in pending_futures:
                task.cancel()

        for _ in range(num_remaining):
            self.queue.task_done()
