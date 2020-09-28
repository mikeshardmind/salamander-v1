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
import threading
from typing import Dict, List, Optional


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


def cancel_all_tasks(loop: asyncio.AbstractEventLoop):
    to_cancel = asyncio.all_tasks(loop)
    if not to_cancel:
        return

    for task in to_cancel:
        task.cancel()

    loop.run_until_complete(
        asyncio.gather(*to_cancel, loop=loop, return_exceptions=True)
    )

    for task in to_cancel:
        if task.cancelled():
            continue
        if task.exception() is not None:
            loop.call_exception_handler(
                {
                    "task": task,
                    "exception": task.exception(),
                    "message": "Unhandled exception during event loop finalization.",
                }
            )
