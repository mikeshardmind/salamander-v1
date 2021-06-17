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

from datetime import timedelta
from typing import Final, Iterator, List, Optional, Sequence, Tuple

__all__ = [
    "format_list",
    "humanize_seconds",
    "humanize_timedelta",
    "pagify",
]


PERIODS: Final[Sequence[Tuple[str, str, int]]] = (
    ("year", "years", 60 * 60 * 24 * 365),
    ("month", "months", 60 * 60 * 24 * 30),
    ("day", "days", 60 * 60 * 24),
    ("hour", "hours", 60 * 60),
    ("minute", "minutes", 60),
    ("second", "seconds", 1),
)


def format_list(to_format: Sequence[str], *, joiner: str = "and") -> str:
    """
    Formats a sequence of strings for display.

    Opinionated choices on formatting below.

    Single item sequences return their only item
    Two items return the items seperated by and,
    Three or more returns a comma seperated list
    with the last values having "and"
    (or other providided joiner)
    but without an oxford comma.

    Raises
    ------
    ValueError
        empty sequence

    Returns
    -------
    str
    """

    length = len(to_format)

    if length == 0:
        raise ValueError("Must provide at least one item")

    if length == 2:
        return " and ".join(to_format)
    if length > 2:
        *most, last = to_format
        # I really wanna leave out that oxford comma
        return f'{", ".join(most)} {joiner} {last}'
    return next(iter(to_format))


def pagify(
    text: str,
    *,
    page_size: int = 1800,
    delims: Optional[List[str]] = None,
    strip_before_yield: bool = True,
) -> Iterator[str]:

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
