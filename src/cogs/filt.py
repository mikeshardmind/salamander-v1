from __future__ import annotations


from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from ..bot import Salamander
else:
    Salamander = commands.Bot


class FilterDemo(commands.Cog):

    bot: Salamander

    def __init__(self, bot):
        self.bot: Salamander = bot

    @commands.Cog.listener("on_message")
    async def on_message(self, msg: discord.Message):

        if msg.content and (not msg.author.bot):

            if await self.bot.check_basalisk(msg.content):
                await msg.channel.send("Found link...")

    