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

import math
import re
from datetime import timedelta
from typing import Final, Optional, Union

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


def parse_positive_number(
    argument: str, upper_bound: Union[int, float] = 18446744073709551615
) -> Optional[int]:
    """
    Parse a positive number with an inclusive upper bound
    """
    lexical_length = math.floor(math.log(upper_bound + 1, 10) + 1)

    if m := re.match(r"([0-9]{1,%s})$" % lexical_length, argument):
        if 0 < (val := int(m.group(1))) <= upper_bound:
            return val

    return None


def parse_snowflake(argument: str) -> Optional[int]:

    if m := re.match(r"([0-9]{7,20})$", argument):
        return int(m.group(1))

    return None
