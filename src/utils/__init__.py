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

from .async_utils import Waterfall as Waterfall
from .converters import (
    StrictMemberConverter as StrictMemberConverter,
    TimedeltaConverter as TimedeltaConverter,
    Weekday as Weekday,
    resolve_as_roles as resolve_as_roles,
)
from .cya import (
    AlreadyDone as AlreadyDone,
    Choice as Choice,
    ChooseYourOwnAdventure as ChooseYourOwnAdventure,
    CYAException as CYAException,
    Decision as Decision,
    InvalidState as InvalidState,
    NoMatchingChoice as NoMatchingChoice,
    NotDone as NotDone,
    Termination as Termination,
)
from .embed_generators import embed_from_member as embed_from_member
from .emoji_handling import (
    add_variation_selectors_to_emojis as add_variation_selectors_to_emojis,
    strip_variation_selectors as strip_variation_selectors,
)
from .formatting import (
    format_list as format_list,
    humanize_seconds as humanize_seconds,
    humanize_timedelta as humanize_timedelta,
    pagify as pagify,
)
from .runtime_utils import MainThreadSingletonMeta as MainThreadSingletonMeta, only_once as only_once

__all__ = [
    "AlreadyDone",
    "CYAException",
    "Choice",
    "ChooseYourOwnAdventure",
    "Decision",
    "InvalidState",
    "MainThreadSingletonMeta",
    "NoMatchingChoice",
    "NotDone",
    "StrictMemberConverter",
    "Termination",
    "TimedeltaConverter",
    "Waterfall",
    "Weekday",
    "add_variation_selectors_to_emojis",
    "async_utils",
    "cya",
    "embed_from_member",
    "format_list",
    "formatting",
    "humanize_seconds",
    "humanize_timedelta",
    "only_once",
    "pagify",
    "resolve_as_roles",
    "runtime_utils",
    "strip_variation_selectors",
]
