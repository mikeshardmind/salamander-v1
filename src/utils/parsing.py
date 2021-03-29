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
import sys
from datetime import timedelta
from decimal import Decimal
from typing import Final, Optional, Union

from dateutil.relativedelta import relativedelta

#: It sucks to have a mathematically sound solution fail on an implementation detail of floats
_2EPSILON: Final[float] = sys.float_info.epsilon * 2


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
        r"((?P<years>\d+?)\s?(years?|y))?" r"((?P<months>\d+?)\s?(months?|mo))?" r"((?P<weeks>\d+?)\s?(weeks?|w))?",
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


def parse_positive_number(argument: str, upper_bound: Union[int, float] = 18446744073709551615) -> Optional[int]:
    """
    Parse a positive number with an inclusive upper bound
    """
    # Additionally, if it causes an issue by going over in any larger case,
    # it still gets handled reasonably.
    #
    # python3.9 adds math.nextafter(float, towards) which would be more correct here,
    # but ultimately not needed
    # Trivial failure case of the pure solution below.
    #
    # prior: int(math.log(upper_bound, 10)) + 1
    # failure case: upper_bound = 1000

    if upper_bound < 1:
        raise ValueError("Must provide a positive non-zero upper bound")

    # Decimal module is sloweer but works with arbitrarily large numbers while being faster than len(str(num))
    # Realistically, I can just change the entire thing to the latter form
    # But... this isn't costing anything to keep.
    log = math.log(upper_bound, 10)
    lexical_length = int(log + _2EPSILON) + 1 if math.isfinite(log) else Decimal(upper_bound).log10() + 1

    if m := re.match(r"([0-9]{1,%s})$" % lexical_length, argument):
        if 0 < (val := int(m.group(1))) <= upper_bound:
            return val

    return None


def parse_snowflake(argument: str) -> Optional[int]:

    if m := re.match(r"([0-9]{7,20})$", argument):
        return int(m.group(1))

    return None
