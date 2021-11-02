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

import asyncio
import contextlib
import json
import logging
import random
from datetime import datetime, timezone
from fractions import Fraction
from typing import Iterable, Optional, TypeVar, MutableMapping

import apsw
import discord
from discord.ext import commands
from lru import LRU

from ...bot import Salamander, SalamanderContext, UserFeedbackError, get_contrib_data_path
from ...checks import admin_or_perms


class AccountAgeGate(commands.Cog):
    """ The current version of this should not be loaded by most servers. """

    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot
        path = get_contrib_data_path("accountagegate")
        self._conn = apsw.Connection(str(path))
        self._cache: MutableMapping[int, int] = LRU(512)

        cursor = self._conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER NOT NULL PRIMARY KEY,
                active BOOLEAN DEFAULT false,
                seconds_offset INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS autobans (
                guild_id INTEGER NOT NULL
                    REFERENCES
                        guild_settings(guild_id)
                        ON UPDATE CASCADE ON DELETE RESTRICT,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );
            """
        )

    @commands.Cog.listener("on_member_join")
    async def mjoin(self, member: discord.Member):
        """
        I still personally think this is a dumb
        metric for banning and don't reccomend it for general use -- Sinbad
        """

        guild = member.guild

        if not guild.me.guild_permissions.ban_members:
            return

        min_age = self._cache.get(guild.id, None)

        if min_age is None:
            # This ensures that without an active row, we still cache enough to work with
            min_age, = self._conn.cursor().execute(
                """
                WITH gs AS (
                    SELECT seconds_offset
                    FROM guild_settings
                    WHERE active AND guild_id = ?
                ),
                gs_defaults AS (
                    SELECT 0 as seconds_offset
                )
                SELECT * FROM gs
                UNION ALL
                SELECT * FROM gs_defaults WHERE NOT EXISTS (SELECT * FROM gs)
                """,
                (guild.id,),
            ).fetchone()

            self._cache[member.guild.id] = min_age
        
        if min_age == 0:
            return
        
        now = datetime.now(timezone.utc)

        if (now - member.created_at).total_seconds() < min_age:
            await member.ban(reason="Account age (automated ban)")
            self.bot.modlog.member_ban(guild.me, member, "[AccountAgeGate] Account age")
            self._conn.cursor().execute(
                """
                INSERT INTO autobans (guild_id, user_id) VALUES (?,?)
                """,
                (guild.id, member.id),
            )