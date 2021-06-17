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

import threading
from typing import Any, Callable, Dict
from typing_extensions import ParamSpec

__all__ = ["MainThreadSingletonMeta", "only_once"]


P = ParamSpec("P")


def only_once(f: Callable[P, Any]) -> Callable[P, None]:
    """
    This isn't threadsafe, might need some guards on this later, but
    it's currently only for use in setting up logging,
    which is also not threadsafe.

    Don't use on other things without accounting for this.
    """
    has_called = False

    def wrapped(*args: P.args, **kwargs: P.kwargs) -> None:
        nonlocal has_called

        if not has_called:
            has_called = True
            f(*args, **kwargs)

        return None

    return wrapped


class MainThreadSingletonMeta(type):

    _instances: Dict[type, object] = {}

    def __call__(cls, *args: Any, **kwargs: Any):

        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("This class may only be instantiated from the main thread")

        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]
