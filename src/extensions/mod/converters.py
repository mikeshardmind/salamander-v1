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

import argparse
import asyncio
import re
import shlex
from datetime import timedelta
from typing import Final, Iterator, NamedTuple, Sequence, TypeVar

import discord
from discord.ext import commands

from ...bot import SalamanderContext
from ...utils.parsing import parse_timedelta

_id_regex: Final[re.Pattern] = re.compile(r"([0-9]{15,21})$")
_mention_regex: Final[re.Pattern] = re.compile(r"<@!?([0-9]{15,21})>$")

__all__ = ("MultiBanConverter",)


T = TypeVar("T")


def list_chunker(iter: Sequence[T], size: int) -> Iterator[Sequence[T]]:  # Consider exposing this
    if size < 1:
        raise ValueError("Chunk size must be greater than 0.")
    for i in range(0, len(iter), size):
        yield iter[i : (i + size)]


class NoExitParser(argparse.ArgumentParser):
    def error(self, message):
        raise commands.BadArgument()


class MultiBanConverter(NamedTuple):
    """
    Handles strict matching semantics + multiple targets, search, and reason
    """

    matched_members: list[discord.Member]
    unmatched_user_ids: list[int]
    reason: str

    @classmethod
    async def convert(cls, ctx: SalamanderContext, arg: str) -> MultiBanConverter:

        parser = NoExitParser(description="MultiBan", add_help=False, allow_abbrev=True)

        parser.add_argument("--reason", dest="reason", nargs="*", default=[])
        parser.add_argument("--members", dest="members", nargs="*", default=[])

        try:
            ns = parser.parse_args(shlex.split(arg))
        except Exception:
            raise commands.BadArgument()

        bot = ctx.bot
        guild = ctx.guild
        if not guild:
            raise commands.NoPrivateMessage()

        reason = " ".join(ns.reason)

        if not reason:
            raise commands.BadArgument("Must provide a ban reason.")

        matched_members: list[discord.Member] = []
        seen_ids: set[int] = set()
        to_search: set[int] = set()

        for argument in ns.members:

            if re_match := (_id_regex.match(argument) or _mention_regex.match(argument)):
                uid = int(re_match.group(1))

                if uid in seen_ids:
                    continue
                else:
                    seen_ids.add(uid)

                member = guild.get_member(uid) or next((m for m in ctx.message.mentions if m.id == uid), None)

                if member:
                    matched_members.append(member)
                else:
                    to_search.add(uid)

        # DEP WARN: bot._get_websocket, guild._state._member_cache_flags
        ws = bot._get_websocket(shard_id=guild.shard_id)

        fails = 0

        for chunk in list_chunker(list(to_search), 100):

            while ws.is_ratelimited():
                fails += 1
                if fails > 3:
                    raise commands.BadArgument("Try again later.")
                await asyncio.sleep(fails)

            members = await guild.query_members(limit=100, user_ids=chunk)

            for member in members:
                to_search.remove(member.id)
                matched_members.append(member)

        if not len(matched_members) + len(to_search):
            raise commands.BadArgument("Must provide at least 1 user to ban.")

        return cls(matched_members, list(to_search), reason)


class SearchBanConverter(NamedTuple):
    matched_members: list[discord.Member]
    unmatched_user_ids: list[int]
    reason: str

    @classmethod
    async def convert(cls, ctx: SalamanderContext, arg: str):

        parser = NoExitParser(description="SearchBan", add_help=False, allow_abbrev=True)
        parser.add_argument("--reason", dest="reason", nargs="*", default=[])
        parser.add_argument("--no-pfp", dest="nopfp", action="store_true", default=False)
        parser.add_argument("--no-roles", dest="noroles", action="store_true", default=False)
        parser.add_argument("--joined-server-within", dest="js", default=[], nargs="*")
        parser.add_argument("--joined-discord-within", dest="jd", default=[], nargs="*")
        parser.add_argument("--username", dest="uname", nargs="*")

        try:
            ns = parser.parse_args(shlex.split(arg))
        except Exception:
            raise commands.BadArgument()

        guild = ctx.guild
        if not guild:
            raise commands.NoPrivateMessage()

        reason = " ".join(ns.reason)

        if not reason:
            raise commands.BadArgument("Must provide a ban reason.")

        if not any((ns.nopfp, ns.js, ns.jd, ns.uname, ns.noroles)):
            raise commands.BadArgument("Must provide at least 1 search criterion.")

        joined_server: timedelta | None = None
        if ns.js:
            joined_server = parse_timedelta(" ".join(ns.js))
            if joined_server is None:
                raise commands.BadArgument("That did not appear to be a valid amount of time.")
                # It's allowed to not be provided, but if provided, we won't silent error

        joined_discord: timedelta | None = None
        if ns.jd:
            joined_discord = parse_timedelta(" ".join(ns.jd))
            if joined_discord is None:
                raise commands.BadArgument("That did not appear to be a valid amount of time.")
                # It's allowed to not be provided, but if provided, we won't silent error

        members: list[discord.Member] = []

        uname: str | None = " ".join(ns.uname) if ns.uname else None

        m: discord.Member
        for m in guild.members:

            if uname and uname == m.name:
                continue

            if joined_server and m.joined_at + joined_server < ctx.message.created_at:
                continue

            if joined_discord and m.created_at + joined_discord < ctx.message.created_at:
                continue

            if ns.nopfp and m.avatar is not None:
                continue

            if ns.noroles and m._roles:
                continue

            members.append(m)

        return cls(members, [], reason)
