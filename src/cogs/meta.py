from __future__ import annotations

from discord.ext import commands


class Meta(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.is_owner()
    @commands.command()
    async def shutdown(self, ctx):
        """ Shuts down the bot """
        await self.bot.logout()
