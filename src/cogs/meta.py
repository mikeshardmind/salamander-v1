from __future__ import annotations

import sys

from discord.ext import commands


class Meta(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.is_owner()
    @commands.command()
    async def shutdown(self, ctx):
        """ Shuts down the bot """
        sys.exit(0)
