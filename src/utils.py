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
import operator
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
    Set,
    Tuple,
    TypeVar,
    Union,
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


_CYA_TV = TypeVar("_CYA_TV")


class CYAException(Exception):
    """ Base for all CYA Exceptions """


class InvalidState(Exception):
    """ Raised when an action is being done from an incompatible state """


class AlreadyDone(InvalidState):
    """
    Raised when trying to do something
    incompatible with being at a termination
    """


class NotDone(InvalidState):
    """
    Raised when trying to do something requiring being done while not done
    """


class NoMatchingChoice(CYAException):
    """ Raised if there is no matching choice to a user input """


class Termination(Generic[_CYA_TV]):
    """
    Used in ``ChooseYourOwnAdventure``

    Parameters
    ----------
    result:
        The result attached to reaching this state.
    """

    def __init__(self, result: _CYA_TV):
        self.result: _CYA_TV = result


class Choice:
    """
    Used in ``ChooseYourOwnAdventure``

    Parameters
    ----------
    label: str
        What this option is labeled as
    goto: int
        The page this choice leads to
    match_func: Callable
        Optionally,
        provide a function which takes two strings (the label and user input)
        and returns a bool representing if the user input should
        be considered to select this choice.

        If not provided, strict equality is used.
    """

    def __init__(
        self,
        label: str,
        goto: int,
        match_func: Callable[[str, str], bool] = operator.eq,
    ):
        self.label: str = label
        self.goto: int = goto
        self._match_func: Callable[[str, str], bool] = match_func

    def check_match(self, user_input: str) -> bool:
        """
        Check if user input selects this choice

        Parameters
        ----------
        user_input: str

        Returns
        -------
        bool
        """
        return self._match_func(self.label, user_input)


class Decision:
    """
    Used in ``ChooseYourOwnAdventure``

    Parameters
    ----------
    prompt: str
    choices: Sequence[Choices]
        A sequence of options available at this point.
    """

    def __init__(self, prompt: str, choices: Sequence[Choice]):
        self.prompt = prompt
        self.choices: Sequence[Choice] = choices

    def to_prompt(self) -> str:
        """
        Get a display for this Decision

        This method can be overriden in usable subclasses to customize display
        """
        return "\n".join((self.prompt, "\n", *(c.label for c in self.choices)))


class ChooseYourOwnAdventure(Generic[_CYA_TV]):
    """
    Design of this is very much like a choose your own adventure novel.

    It's actual purpose is complex interactive prompts while still
    preserving type hint compatability,
    The structure of this can't be recursive or self-referrential due to a lack of
    recursive type support, so we cheat a little bit.

    Starting pages should be 0


    >>> adventure = ChooseYourOwnAdventure(
    ...     {
    ...         0: Decision(
    ...             "You are at a cave entrance. It is dark inside",
    ...             [Choice("Stay here", 0), Choice("Leave", 1), Choice("Head inside", 2)],
    ...         ),
    ...         1: Termination("You survived by not playing."),
    ...         2: Termination("You died because this example railroaded you."),
    ...     }
    ... )
    """

    def __init__(
        self,
        initial_pages: Optional[
            Dict[int, Union[Decision, Termination[_CYA_TV]]]
        ] = None,
    ):
        self._pages: Dict[
            int, Union[Decision, Termination[_CYA_TV]]
        ] = initial_pages if initial_pages is not None else {}
        self._pos = 0

    def add_page(
        self, page_number: int, page: Union[Decision, Termination[_CYA_TV]]
    ) -> ChooseYourOwnAdventure[_CYA_TV]:
        """
        Add a page.

        This is an interface which supports fluent chaining

        Parameters
        ----------
        page_number: int
        page: Union[Decision, Termination]

        The below is equivalent to the example provided for creation by passing a dict

        >>> adventure = (
        ...     ChooseYourOwnAdventure()
        ...     .add_page(
        ...         0,
        ...         Decision(
        ...             "You are at a cave entrance. It is dark inside",
        ...             [Choice("Stay here", 0), Choice("Leave", 1), Choice("Head inside", 2)],
        ...         )
        ...     )
        ...     .add_page(1, Termination("You survived by not playing."))
        ...     .add_page(2, Termination("You died because this example railroaded you."))
        ... )
        """
        self._pages[page_number] = page
        return self

    def get_prompt(self) -> str:
        """
        Create a prompt from the current state

        Raises
        ------
        AlreadyDone

        Returns
        -------
        str
        """

        page = self._pages[self._pos]

        if isinstance(page, Termination):
            raise AlreadyDone()

        return page.to_prompt()

    def turn_page(self, choice: str):
        """
        Turns to the page corresponding to a choice

        Raises
        ------
        NoMatchingChoice
        AlreadyDone
        """

        page = self._pages[self._pos]
        if isinstance(page, Termination):
            raise AlreadyDone()

        for c in page.choices:
            if c.check_match(choice):
                self._pos = c.goto
                break
        else:
            raise NoMatchingChoice()

    def check_if_done(self) -> bool:
        """ Returns a bool signifying if we are eat a termination """
        return isinstance(self._pages[self._pos], Termination)

    def get_result(self) -> _CYA_TV:
        """ Get the result

        Raises
        ------
        NotDone
        """
        page = self._pages[self._pos]
        if not isinstance(page, Termination):
            raise NotDone()

        return page.result

    def reset(self):
        """ Resets to the initial state """
        self._pos = 0


def _validate_cya(adventure: ChooseYourOwnAdventure):
    """
    Tool to validate that a ChooseYourOwnAdventure instance is valid
    """

    adventure.reset()
    pages = adventure._pages
    entrypoint = pages.get(0, None)
    if entrypoint is None:
        raise RuntimeError("Must have an entrypoint at page 0")
    if not isinstance(entrypoint, Decision):
        raise RuntimeError("Entrypoint must be a Decision")

    seen: Set[int] = {0}
    unseen: Set[int] = {k for k, v in pages.items() if k}

    def reachable_from(*page_numbers: int) -> Set[int]:
        """ This is 1 choice reachability """

        ret: Set[int] = set()

        for page_num in page_numbers:
            page = pages[page_num]

            if isinstance(page, Decision):
                for choice in page.choices:

                    new_p = pages.get(choice.goto, None)
                    if new_p is None:
                        raise RuntimeError(
                            f"Decision on page {page_num} references "
                            f"non existant page {choice.goto} via "
                            f"choice with label {choice.label}"
                        )

                    if not isinstance(new_p, (Termination, Decision)):
                        raise RuntimeError(
                            f"Got unexpected type {type(new_p)} for page number {choice.goto}"
                        )

                    ret.add(choice.goto)

        return ret

    while (newly_reachable := reachable_from(*seen) - seen) :

        unseen -= newly_reachable
        seen |= newly_reachable

    if unseen:
        raise RuntimeError(f"Some pages were unreachable: {unseen}")

    # Now that we've ruled out unreachable states, we need to ensure there are no states that individually get stuck.
    # An example that the above would not have ruled out:
    # 0 -> 1 or 2, 1 -> 1, 2 -> 3, with 0, 1, 2, as decisions and 3 as a termination

    terminations: Set[int] = {k for k, v in pages.items() if isinstance(k, Termination)}
    decisions: Set[int] = {k for k, v in pages.items() if isinstance(k, Decision)}

    # I imagine there's a more efficient way of doing this, but given the constraints that:
    # 1: This allows loops
    # 2: This doesn't guarantee if backtracking is allowed or not

    # I'm not sure if there actually is,
    # the priority was something that could be run "in a reasonable amount of time" for development, not for production.

    # From every decision state, ensure a termination is reachable
    # This prevents an issue where 1 -> 2, 2 -> 1 "Hey, I'm still going here"

    # If anyone comes across this and knows of a more efficient way, I'd love to hear about it.

    reaches_a_termination: Set[int] = set()

    for start_state in decisions:

        state_seen: Set[int] = {start_state}

        while (state_newly_reachable := reachable_from(*state_seen) - state_seen) :
            for page_number in state_newly_reachable:
                if page_number in reaches_a_termination or page_number in terminations:
                    break
            else:
                state_seen |= state_newly_reachable
                continue
            break
        else:
            raise RuntimeError(f"Cannot reach a termination from page {start_state}")

        reaches_a_termination.add(start_state)
