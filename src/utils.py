#   Copyright 2020 Michael Hall
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
import re
import threading
import time
from datetime import timedelta
from typing import (
    Awaitable,
    Callable,
    Dict,
    Final,
    Generic,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    overload,
)

from dateutil.relativedelta import relativedelta

TIMEDELTA_RE_STRING: Final[str] = r"\s?".join(
    [
        r"((?P<weeks>\d+?)\s?(weeks?|w))?",
        r"((?P<days>\d+?)\s?(days?|d))?",
        r"((?P<hours>\d+?)\s?(hours?|hrs|hr?))?",
        r"((?P<minutes>\d+?)\s?(minutes?|mins?|m(?!o)))?",  # prevent matching "months"
        r"((?P<seconds>\d+?)\s?(seconds?|secs?|s))?",
    ]
)

RELATIVEDELTA_RE_STRING: Final[str] = r"\s?".join(
    [
        r"((?P<years>\d+?)\s?(years?|y))?"
        r"((?P<months>\d+?)\s?(months?|mo))?"
        r"((?P<weeks>\d+?)\s?(weeks?|w))?",
        r"((?P<days>\d+?)\s?(days?|d))?",
        r"((?P<hours>\d+?)\s?(hours?|hrs|hr?))?",
        r"((?P<minutes>\d+?)\s?(minutes?|mins?|m(?!o)))?",  # prevent matching "months"
        r"((?P<seconds>\d+?)\s?(seconds?|secs?|s))?",
    ]
)

TIMEDELTA_RE = re.compile(TIMEDELTA_RE_STRING, re.I)
RELATIVEDELTA_RE = re.compile(RELATIVEDELTA_RE_STRING, re.I)

PERIODS: Final[Sequence[Tuple[str, str, int]]] = (
    ("year", "years", 60 * 60 * 24 * 365),
    ("month", "months", 60 * 60 * 24 * 30),
    ("day", "days", 60 * 60 * 24),
    ("hour", "hours", 60 * 60),
    ("minute", "minutes", 60),
    ("second", "seconds", 1),
)


def parse_timedelta(argument: str) -> Optional[timedelta]:
    matches = TIMEDELTA_RE.match(argument)
    if matches:
        params = {k: int(v) for k, v in matches.groupdict().items() if v}
        if params:
            return timedelta(**params)
    return None


def parse_relativedelta(argument: str) -> Optional[relativedelta]:
    matches = RELATIVEDELTA_RE.match(argument)
    if matches:
        params = {k: int(v) for k, v in matches.groupdict().items() if v}
        if params:
            return relativedelta(None, None, **params)  # The Nones are to satisfy mypy
    return None


def format_list(to_format: Sequence[str]) -> str:
    """ Intentionally raises on empty sequence, opinionated choices on formatting below. Single item sequences return their only item"""

    length = len(to_format)

    if length == 2:
        return " and ".join(to_format)
    if length > 2:
        *most, last = to_format
        # I really wanna leave out that oxford comma
        return f'{", ".join(most)} and {last}'
    return next(iter(to_format))


def pagify(
    text: str,
    *,
    page_size: int = 1800,
    delims: Optional[List[str]] = None,
    strip_before_yield=True,
):

    delims = delims or ["\n"]

    while len(text) > page_size:
        closest_delims = (text.rfind(d, 1, page_size) for d in delims)
        closest_delim = max(closest_delims)
        closest_delim = closest_delim if closest_delim != -1 else page_size

        chunk = text[:closest_delim]
        if len(chunk.strip() if strip_before_yield else chunk) > 0:
            yield chunk
        text = text[closest_delim:]

    if len(text.strip() if strip_before_yield else text) > 0:
        yield text


def only_once(f):
    """
    This isn't threadsafe, might need some guards on this later, but
    it's currently only for use in setting up logging,
    which is also not threadsafe.

    Don't use on other things without accounting for this.
    """
    has_called = False

    def wrapped(*args, **kwargs):
        nonlocal has_called

        if not has_called:
            has_called = True
            f(*args, **kwargs)

    return wrapped


class MainThreadSingletonMeta(type):

    _instances: Dict[type, object] = {}

    def __call__(cls, *args, **kwargs):

        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError(
                "This class may only be instantiated from the main thread"
            )

        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


_T = TypeVar("_T")


class Waterfall(Generic[_T]):
    def __init__(
        self,
        max_wait: float,
        max_quantity: int,
        async_callback: Callable[[Sequence[_T]], Awaitable],
    ):
        asyncio.get_running_loop()
        self.queue = asyncio.Queue()  # type: asyncio.Queue[_T]
        self.max_wait: float = max_wait
        self.max_quantity: int = max_quantity
        self.callback: Callable[[Sequence[_T]], Awaitable] = async_callback
        self.task: Optional[asyncio.Task] = None
        self._alive: bool = False

    def start(self):
        if self.task is not None:
            raise RuntimeError("Already Running")

        self._alive = True
        self.task = asyncio.create_task(self._loop)

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
        while self._alive:
            queue_items: Sequence[_T] = []
            iter_start = time.monotonic()

            while (this_max_wait := (time.monotonic() - iter_start)) < self.max_wait:
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

        # Don't stop entirely until we clear the remainder of the queue

        remaining_items: Sequence[_T] = []

        while not self.queue.empty():
            try:
                ev = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            remaining_items.append(ev)

        num_remaining = len(remaining_items)

        for chunk in (
            remaining_items[p : p + self.max_quantity]
            for p in range(0, num_remaining, self.max_quantity)
        ):
            asyncio.create_task(self.callback(chunk))

        for _ in range(num_remaining):
            self.queue.task_done()


def humanize_seconds(seconds: float) -> str:

    seconds = int(seconds)
    strings = []
    for period_name, plural_period_name, period_seconds in PERIODS:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            if period_value == 0:
                continue
            unit = plural_period_name if period_value > 1 else period_name
            strings.append(f"{period_value} {unit}")

    return format_list(strings)


def humanize_timedelta(delta: timedelta) -> str:
    return humanize_seconds(delta.total_seconds())
