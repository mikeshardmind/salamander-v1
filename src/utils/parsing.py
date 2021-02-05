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

import re
from datetime import timedelta
from typing import Final, Optional

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
