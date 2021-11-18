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

import discord
from discord import flags
from discord.ext import commands

from ...bot import Salamander, SalamanderContext
from ...checks import admin_or_perms


class Tweaks(commands.Cog):
    """Various tweaks for discord behavior."""

    def __init__(self, bot: Salamander) -> None:
        self.bot: Salamander = bot

    @admin_or_perms(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_guild=True)
    @commands.command(name="nowelcomestickers")
    async def disable_welcome_stickers(self, ctx: SalamanderContext):
        """Disable stickers on welcome messages."""
        assert ctx.guild

        flags = ctx.guild.system_channel_flags
        flags.value |= 8
        await ctx.guild.edit(system_channel_flags=flags)
        await ctx.send("Welcome messages won't have sticker prompts anymore.")

    @admin_or_perms(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_guild=True)
    @commands.command(name="bringbackwelcomestickers")
    async def enable_welcome_stickers(self, ctx: SalamanderContext):
        """re-enable stickers on welcome messages."""
        assert ctx.guild

        flags = ctx.guild.system_channel_flags
        flags.value &= ~8
        await ctx.guild.edit(system_channel_flags=flags)
        await ctx.send("I guess if you want them...")