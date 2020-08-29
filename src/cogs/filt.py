from __future__ import annotations


from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from ..bot import Salamander, SalamanderContext
else:
    Salamander = commands.Bot
    SalamanderContext = commands.Context


REFOCUS = "basalisk.refocus"


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
    async def addpattern(self, ctx: SalamanderContext, pattern):
        """ Add a pattern to the scanner """
        self.bot.ipc_put(REFOCUS, ((pattern,), ()))
        await ctx.send("Pattern added.")

    @commands.is_owner()
    @commands.command()
    async def removepattern(self, ctx: SalamanderContext, pattern):
        """ Remove a pattern from the scanner """
        self.bot.ipc_put(REFOCUS, ((), (pattern,)))
        await ctx.send("Pattern removed.")
