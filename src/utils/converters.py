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

import enum
import re
from datetime import timedelta
from typing import Final, NamedTuple, Sequence

import discord
from discord.ext import commands


from .formatting import humanize_timedelta
from .parsing import parse_timedelta

_id_regex: Final[re.Pattern] = re.compile(r"([0-9]{15,21})$")
_mention_regex: Final[re.Pattern] = re.compile(r"<@!?([0-9]{15,21})>$")
_role_mention_regex: Final[re.Pattern] = re.compile(r"^<@&([0-9]{15,21})>$")


class WeekdayChoices(enum.Enum):
    Monday = 0
    Tuesday = 1
    Wednesday = 2
    Thursday = 3
    Friday = 4
    Saturday = 5
    Sunday = 6


class Weekday:

    _valid_days = {
        0: ("monday", "m", "mon"),
        1: ("tuesday", "t", "tu", "tue", "tues"),
        2: ("wednesday", "w", "wed"),
        3: ("thursday", "th", "r", "thu", "thur", "thurs"),
        4: ("friday", "f", "fri"),
        5: ("saturday", "sat", "sa", "s"),
        6: ("sunday", "sun", "su", "u"),
    }

    def __init__(self, number: int):
        self.number: int = number

    def as_string(self):
        return self._valid_days[self.number][0].title()

    def __repr__(self):
        return f"<Weekday({self.number})>"

    def __str__(self):
        return self.as_string()

    @classmethod
    async def convert(cls, ctx, argument: str):

        argument = argument.strip().casefold()

        for number, opts in cls._valid_days.items():
            if argument in opts:
                return cls(number)

        raise commands.BadArgument(message="I didn't understand that input as a day of the week")


class TimedeltaConverter(NamedTuple):
    arg: str
    delta: timedelta

    @classmethod
    async def convert(cls, ctx, argument: str):

        parsed = parse_timedelta(argument)
        if not parsed:
            raise commands.BadArgument(message="That wasn't a duration of time.")

        return cls(argument, parsed)

    def __str__(self):
        return humanize_timedelta(self.delta)


def resolve_as_roles(guild: discord.Guild, user_input: str) -> Sequence[discord.Role]:

    if match := (_id_regex.match(user_input) or _role_mention_regex.match(user_input)):
        # We assume that nobody will make a role with a name that is an ID
        # If someone reports this as a bug,
        # kindly tell them to change the name of the impacted role.
        if role := guild.get_role(int(match.group(1))):
            return (role,)

    casefolded_user_input = user_input.casefold()
    return tuple(r for r in guild.roles if r.name.casefold() == casefolded_user_input)


class StrictMemberConverter(NamedTuple):
    """
    Forces some stricter matching semantics

    Always matches a user input as a converter, some fields may result optional.
    This is intentional for ease of use with `ignore_extra=False` in commands, as well as
    making it easier to tailor error messages raised.

    Matches by exact ID or mention match or Username#discrim

    It can fail to find a valid existing match if over 100 users in a server
    have the exact same username and Username#discrim is used with a non-cached member list,
    or if discord raises an http exception in an unexpected manner with a non-cached member list.
    """

    user_input: str
    member: discord.Member | None
    id: int | None

    @classmethod
    async def convert(cls, ctx, argument):
        bot = ctx.bot
        guild = ctx.guild

        if re_match := (_id_regex.match(argument) or _mention_regex.match(argument)):
            uid = int(re_match.group(1))

            member = guild.get_member(uid) or next((m for m in ctx.message.mentions if m.id == uid), None)

            if member:
                return cls(argument, member, uid)

            # DEP WARN: bot._get_websocket, guild._state._member_cache_flags
            ws = bot._get_websocket(shard_id=guild.shard_id)
            if ws.is_ratelimited():
                try:
                    member = await guild.fetch_member(uid)
                    if guild._state._member_cache_flags.joined:
                        guild._add_member(member)
                    return cls(argument, member, uid)
                except discord.NotFound:
                    return cls(argument, None, uid)
                except discord.HTTPException:
                    return cls(argument, None, None)
            else:
                members = await guild.query_members(limit=1, user_ids=[uid])
                if not members:
                    return cls(argument, None, uid)
                member = members[0]
                return cls(argument, member, uid)

        elif len(argument) > 5 and argument[-5] == "#":
            name, _hash, discrim = argument.rpartition("#")
            member = next(
                (m for m in guild.members if m.name == name and m.discriminator == discrim),
                None,
            )
            if member:
                return cls(argument, member, member.id)
            members = await guild.query_members(name, limit=100)
            member = next(
                (m for m in members if m.name == name and m.discriminator == discrim),
                None,
            )
            uid = member.id if member else None
            return cls(argument, member, uid)

        else:
            return cls(argument, None, None)
