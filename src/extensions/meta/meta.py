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

import discord
from discord.ext import commands

from ...bot import Salamander, SalamanderContext, UserFeedbackError
from ...checks import admin_or_perms


class Meta(commands.Cog):
    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot

    @commands.is_owner()
    @commands.command()
    async def shutdown(self, ctx: SalamanderContext):
        """ Shuts down the bot """
        await self.bot.logout()

    @admin_or_perms(manage_guild=True)
    @commands.command()
    async def prefix(self, ctx: SalamanderContext):
        """ Commands for managing the bot's prefix in this server """
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @prefix.command(name="list")
    async def prefix_list(self, ctx: SalamanderContext):
        """ List the prefixes currently configured for this server """

        prefixes = self.bot.prefix_manager.get_guild_prefixes(ctx.guild.id)[::-1]
        em = discord.Embed(title="Configured Prefixes", color=ctx.me.color)
        em.set_footer(text="You can also start your command by mentioning me.")
        em.description = "\n".join(
            f"{index}. `{prefix}`" for index, prefix in enumerate(prefixes, 1)
        )
        await ctx.send(embed=em)

    @prefix.command(name="add", ignore_extra=True)
    async def prefix_add(self, ctx: SalamanderContext, prefix: str):
        """
        Add a prefix

        If you would like your prefix to end in a space, make sure you use quates.
        (Discord removes trailing whitespace from messages)

        Multi-word prefixes should also be quoted.
        """

        current_prefixes = self.bot.prefix_manager.get_guild_prefixes(ctx.guild.id)
        if len(current_prefixes) >= 5:
            raise UserFeedbackError(
                custom_message="You cannot configure more than 5 custom prefixes."
            )

        for special_char_sequence in ("*", "`", "_", "~", "|", ">>>", "'", '"'):
            if special_char_sequence in prefix:
                raise UserFeedbackError(
                    custom_message=f"Prefixes may not contain {special_char_sequence}"
                )
        if prefix.startswith((f"<@{ctx.me.id}>", f"<@!{ctx.me.id}>")):
            raise UserFeedbackError(
                custom_message="You don't need to configure mentions as a prefix."
            )

        if len(prefix) > 15:
            raise UserFeedbackError(custom_message="Let's not add a prefix that long.")

        self.bot.prefix_manager.add_guild_prefixes(ctx.guild.id, prefix)
        await ctx.send("Prefix added.")

    @prefix.command(name="remove", aliases=["delete"], ignore_extra=True)
    async def prefix_remove(self, ctx: SalamanderContext, prefix: str):
        """
        Remove a prefix

        If referring to a prefix which ends in a space, make sure you use quates.
        (Discord removes trailing whitespace from messages)

        Multi-word prefixes should also be quoted.
        """
        if prefix.startswith((f"<@{ctx.me.id}>", f"<@!{ctx.me.id}>")):
            raise UserFeedbackError(
                custom_message="I won't remove mentioning me as a prefix"
            )

        current_prefixes = self.bot.prefix_manager.get_guild_prefixes(ctx.guild.id)
        if prefix not in current_prefixes:
            raise UserFeedbackError(
                custom_message="That isn't a current prefix, so there's nothing to remove."
            )

        self.bot.prefix_manager.remove_guild_prefixes(ctx.guild.id, prefix)

    @prefix_remove.error
    @prefix_add.error
    async def prefix_addremove_too_many_argy(self, ctx: SalamanderContext, exc):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send(
                "I can only add one prefix at a time. "
                "If you intended that as a singular prefix, please quote it."
            )
