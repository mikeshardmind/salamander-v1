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
import logging
import re
from uuid import uuid4

import discord
from discord.ext import commands

from ...bot import Salamander, SalamanderContext
from ...checks import admin_or_perms

BASILISK = "basilisk"
REFOCUS = "basilisk.refocus"
STATUS_CHECK = "status.check"
STATUS_RESPONSE = "status.response"

CONTENT_TYPE_PATTERN = re.compile(r"; charset=(.*)$")
MAX_REASONABLE_TEXT_SIZE = 128_000

log = logging.getLogger("salamander.filter")


class Filter(commands.Cog):

    bot: Salamander

    def __init__(self, bot):
        self.bot: Salamander = bot

    def check_enabled_in_guild(self, guild_id: int) -> bool:

        cursor = self.bot._conn.cursor()
        cursor.execute(
            """
            SELECT feature_flags & 1 FROM guild_settings WHERE guild_id = ?
            """,
            (guild_id,),
        )
        if row := cursor.fetchone():
            return row[0]
        return False

    def disable_in_guild(self, guild_id: int):
        cursor = self.bot._conn.cursor()
        cursor.execute(
            """
            UPDATE guild_settings
            SET feature_flags=feature_flags & ~1
            WHERE guild_id = ?
            """,
            (guild_id,),
        )

    def enable_in_guild(self, guild_id: int):
        cursor = self.bot._conn.cursor()
        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id, feature_flags)
            VALUES (?, 1)
            ON CONFLICT (guild_id)
            DO UPDATE SET feature_flags=feature_flags | 1
            """,
            (guild_id,),
        )

    @commands.Cog.listener("on_message")
    async def on_message(self, msg: discord.Message):

        if msg.author.bot:
            return

        if not msg.guild:
            return

        if isinstance(msg.channel, discord.PartialMessageable):
            return

        if not msg.channel.permissions_for(msg.guild.me).manage_channels:
            return

        if not self.check_enabled_in_guild(msg.guild.id):
            return

        if msg.content and await self.bot.check_basilisk(msg.content):
            await msg.delete()
            return

        for attachment in msg.attachments:
            if not attachment.content_type:
                continue
            if match := CONTENT_TYPE_PATTERN.search(attachment.content_type):
                encoding = match.group(1)

                if attachment.size > MAX_REASONABLE_TEXT_SIZE:
                    await msg.delete()
                    return

                try:
                    data = (await attachment.read()).decode(encoding=encoding)
                except LookupError:
                    log.exception("Got unknown encoding %s", encoding)
                    await msg.delete()
                except UnicodeDecodeError:
                    # Well, yes it can happen.
                    # I don't know why I expected otherwise
                    # given the issues with their media renderer.
                    # I guess I figured this was too hard for them to screw up.
                    # because of how easy it is to not show malformed unicode.
                    # Rather than reject to render the file,
                    # they just assume it should be shown.
                    # and fill unknown byte sequences with U+FFFD
                    # While I could do similar using errors='replace'
                    # I have no interest in such.
                    await msg.delete()
                else:
                    if await self.bot.check_basilisk(data):
                        await msg.delete()
                        return

    @admin_or_perms(manage_guild=True)
    @commands.group(name="filterset")
    async def filterset(self, ctx: SalamanderContext):
        """Commands for managing the network filter"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @admin_or_perms(manage_guild=True)
    @filterset.command()
    async def enable(self, ctx: SalamanderContext):
        """Enable the network wide filter in this server"""
        assert ctx.guild is not None
        self.enable_in_guild(ctx.guild.id)
        await ctx.send("Filtering enabled.")

    @admin_or_perms(manage_guild=True)
    @filterset.command()
    async def disable(self, ctx: SalamanderContext):
        """Disable the network wide filter in this server"""
        assert ctx.guild is not None
        self.disable_in_guild(ctx.guild.id)
        await ctx.send("Filtering disabled.")

    @commands.is_owner()
    @filterset.command()
    async def addpattern(self, ctx: SalamanderContext, *, pattern):
        """Add a pattern to the scanner"""
        self.bot.ipc_put(REFOCUS, ((pattern,), ()))
        await ctx.send("Pattern added.")

    @commands.is_owner()
    @filterset.command()
    async def removepattern(self, ctx: SalamanderContext, *, pattern):
        """Remove a pattern from the scanner"""
        self.bot.ipc_put(REFOCUS, ((), (pattern,)))
        await ctx.send("Pattern removed.")

    @admin_or_perms(manage_guild=True)
    @filterset.command()
    async def listpatterns(self, ctx: SalamanderContext):
        """List the current patterns being filtered"""

        this_uuid = uuid4().bytes

        def matches(*args) -> bool:
            topic, (recv_uuid, component_name, *_data) = args
            return topic == STATUS_RESPONSE and recv_uuid == this_uuid and component_name == BASILISK

        f = self.bot.wait_for("ipc_recv", check=matches, timeout=5)

        self.bot.ipc_put(STATUS_CHECK, this_uuid)

        try:
            _topic, (_muuid, _component_name, _uptime, data) = await f
        except asyncio.TimeoutError:
            await ctx.send("No response from filtering service.")
        else:
            patterns = data.get("patterns", None)
            if patterns:
                await ctx.send_paged(
                    "\n".join(patterns),
                    box=True,
                    prepend="Currently using the following patterns\n\n",
                )
            else:
                await ctx.send("No current patterns")
