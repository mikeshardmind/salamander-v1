from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from ..bot import Salamander, SalamanderContext
else:
    Salamander = commands.Bot
    SalamanderContext = commands.Context


BASALISK = "basalisk"
REFOCUS = "basalisk.refocus"
STATUS_CHECK = "status.check"
STATUS_RESPONSE = "status.response"


class FilterDemo(commands.Cog):

    bot: Salamander

    def __init__(self, bot):
        self.bot: Salamander = bot

    @commands.Cog.listener("on_message")
    async def on_message(self, msg: discord.Message):

        if msg.content and (not msg.author.bot):

            if await self.bot.check_basalisk(msg.content):
                await msg.channel.send("Found match")

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
