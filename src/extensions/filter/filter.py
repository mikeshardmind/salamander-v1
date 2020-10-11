#   Copyright 2020 Michael Hall
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
from uuid import uuid4

import discord
from discord.ext import commands

from ...bot import Salamander, SalamanderContext

BASALISK = "basalisk"
REFOCUS = "basalisk.refocus"
STATUS_CHECK = "status.check"
STATUS_RESPONSE = "status.response"


class Filter(commands.Cog):

    bot: Salamander

    def __init__(self, bot):
        self.bot: Salamander = bot

    @commands.Cog.listener("on_message")
    async def on_message(self, msg: discord.Message):

        if msg.content and (not msg.author.bot) and msg.guild:
            if msg.channel.permissions_for(msg.guild.me).manage_messages:
                if await self.bot.check_basalisk(msg.content):
                    await msg.delete()

    @commands.is_owner()
    @commands.command()
    async def addpattern(self, ctx: SalamanderContext, *, pattern):
        """ Add a pattern to the scanner """
        self.bot.ipc_put(REFOCUS, ((pattern,), ()))
        await ctx.send("Pattern added.")

    @commands.is_owner()
    @commands.command()
    async def removepattern(self, ctx: SalamanderContext, *, pattern):
        """ Remove a pattern from the scanner """
        self.bot.ipc_put(REFOCUS, ((), (pattern,)))
        await ctx.send("Pattern removed.")

    @commands.is_owner()
    @commands.command()
    async def listpatterns(self, ctx: SalamanderContext):
        """ List the current patterns being filtered """

        this_uuid = uuid4().bytes

        def matches(*args) -> bool:
            topic, (recv_uuid, component_name, *_data) = args
            return (
                topic == STATUS_RESPONSE
                and recv_uuid == this_uuid
                and component_name == BASALISK
            )

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
