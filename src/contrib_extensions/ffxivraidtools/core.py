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

from datetime import datetime
from typing import Literal, Optional, Sequence, TypedDict

import attr

BARRIER_TYPE = Literal["SCH", "SGE"]
REGEN_TYPE = Literal["AST", "WHM"]
HEALER_TYPE = Literal["AST", "WHM", "SCH", "SGE"]
JOB_TYPE = Literal[
    "PLD", "WAR", "DRK", "GNB", "MNK", "DRG", "NIN", "SAM", "RPR", "BRD", "MCH", "DNC", "BLM", "SMN", "RDM"
]

TANKS = ("PLD", "WAR", "DRK", "GNB")
MELEE = ("MNK", "DRG", "NIN", "SAM", "RPR")
RANGED_PHYSICAL = ("BRD", "MCH", "DNC")
CASTER = ("BLM", "SMN", "RDM")

REGEN: Sequence[REGEN_TYPE] = ("WHM", "AST")
BARRIER: Sequence[BARRIER_TYPE] = ("SCH", "SGE")
HEALERS: Sequence[HEALER_TYPE] = ("WHM", "AST", "SCH", "SGE")

RANGED = CASTER + RANGED_PHYSICAL
DPS = RANGED + MELEE  # I mean all, but for comp purposes....


class _HT(TypedDict):
    Savage: tuple[Sequence[BARRIER_TYPE], Sequence[REGEN_TYPE]]
    NoDoubleBarrier: tuple[Sequence[REGEN_TYPE], Sequence[HEALER_TYPE]]
    Any: tuple[Sequence[HEALER_TYPE], Sequence[HEALER_TYPE]]


HEALER_LOOKUPS = _HT(
    Savage=(BARRIER, REGEN),
    NoDoubleBarrier=(REGEN, HEALERS),
    Any=(HEALERS, HEALERS),
)


@attr.s(slots=True, auto_attribs=True)
class Instance:
    name: str
    lv: int
    min_ilv: int
    rec_ilv: int
    composition: Literal["Alliance", "Savage", "Raid", "Trial", "Extreme", "Dungeon"]
    healer_mode: Literal["Savage", "NoDoubleBarrier", "Any"]
    enforce_maximum_comp_buff: Optional[bool] = None
    #: Even if set, will be ignored in Alliance Raids and Dungeons
    enforce_double_melee: bool = False
    #: info to be displayed in chat
    extra_info: Optional[str] = None

    def get_composition(self):
        """Gets a valid composition template  for the instance."""

        if self.composition == "Dungeon":
            return (TANKS, HEALERS, DPS, DPS)

        if self.composition == "Alliance":
            return (TANKS, HEALERS, DPS, DPS, DPS, DPS, DPS)

        if self.enforce_maximum_comp_buff is not None:
            enforce = self.enforce_maximum_comp_buff
        else:
            enforce = bool(self.composition == "Savage")

        if enforce:
            base = (TANKS, TANKS, MELEE, RANGED_PHYSICAL, CASTER) + ((MELEE,) if self.enforce_double_melee else (DPS,))
        else:
            base = (TANKS, TANKS, DPS, DPS, DPS, DPS)

        return base + HEALER_LOOKUPS[self.healer_mode]


@attr.s(slots=True, auto_attribs=True)
class Player:
    ign: str
    server: str
    discord_id: int


@attr.s(slots=True, auto_attribs=True)
class PlayerJob:
    player: Player
    job: JOB_TYPE
    ilv: int


@attr.s(slots=True, auto_attribs=True)
class ScheduledInstance:
    """
    We *do* assume the host must be present and on a single role, not flexing.
    This avoids a case where a match can't be found containing the host
    without resorting to horrible time complexity searches.
    """
    host: PlayerJob
    instance: Instance
    time: datetime
    event_uuid: str


@attr.s(slots=True, auto_attribs=True)
class Registration:
    # Players may register multiple times, for each job they are willing to join on
    who: PlayerJob
    event: ScheduledInstance
    signup_time: datetime


def composition_filler(instance: Instance, canidates: Sequence[Registration]) -> Sequence[Registration]:
    """
    This is likely going to need multiple iterations to ensure fairness
    as multiple critiera are going to be present here
    """
    ret: list[Registration] = []

    comp = instance.get_composition()

    split_canidates = {index: [c for c in canidates if c.who.job in job_spec] for index, job_spec in enumerate(comp, 0)}

    while split_canidates:
        # take from the smallest canidate pools relative to the need first

        # We know there to be at least 1, this doesn't need a guard
        index, current_canidates = next(iter(sorted(split_canidates.items(), key=lambda kv: 1 - len(kv[1]))))

        if not current_canidates:
            # This should probably only be possible when lacking enough canidates right now.
            raise RuntimeError(f"figure this out yourself (for now...) ")
        else:
            # Yes, this implicitly deprioritizes people the more they flex.
            # I don't have a good solution for this right now.
            # The "check all the options" solution is easy to show not to be viable.
            # Consider 10 people who play 6 jobs each, that's 60 choose 8, then filter on validity
            # and not far fetched based on survey data as a *lower* bound
            # A solution utilizing disjoint sets could avoid this deprioritization,
            # and that's a level of effort I'm going to ignore until later.
            def queue_count(u: Registration) -> int:
                r = 0
                for _l in split_canidates.values():
                    for _ in _l:
                        if _.who.player.discord_id == u.who.player.discord_id:
                            r += 1
                return r

            entry = next(iter(sorted(current_canidates, key=lambda x: (queue_count(x), x.signup_time))))
            ret.append(entry)
            del split_canidates[index]

            for index, cc in split_canidates.items():
                cc[:] = [c for c in cc if c.who.player.discord_id != entry.who.player.discord_id]

    ret.sort(key=lambda x: (x.who.job, x.who.player.discord_id))
    return ret
