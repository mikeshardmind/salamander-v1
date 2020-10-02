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

from typing import Union

import discord
from discord.ext import commands

from ...bot import HierarchyException, Salamander, SalamanderContext, UserFeedbackError


def kick_sanity_check(
    bot_user: discord.Member, mod: discord.Member, target: discord.Member
):

    if target == mod:
        raise UserFeedbackError(
            custom_message=(
                "You can't kick yourself, "
                "but Discord does have an option to leave servers."
            )
        )

    if target == bot_user:
        raise UserFeedbackError(
            custom_message=(
                "I can't kick myself from the server. "
                "If you don't want me here, use the leave command instead."
            )
        )

    if target.guild.owner == target:
        raise HierarchyException(custom_message="You can't kick the owner of a guild.")

    if not mod.guild.owner == mod:
        if target.top_role == mod.top_role:
            raise HierarchyException(
                custom_message="You can't kick someone with the same top role as you."
            )

        if target.top_role > mod.top_role:
            raise HierarchyException(
                custom_message="You can't kick someone with a higher top role than you."
            )

    if not bot_user.guild.owner == bot_user:
        if target.top_role == bot_user.top_role:
            raise HierarchyException(
                custom_message="I can't kick someone with the same top role as me."
            )

        if target.top_role >= bot_user.top_role:
            raise HierarchyException(
                custom_message="I can't kick someone with a higher top role than me."
            )


def ban_sanity_check(
    bot_user: discord.Member, mod: discord.Member, target: discord.Member,
):

    if target == mod:
        raise UserFeedbackError(
            custom_message=(
                "You can't ban yourself, "
                "but Discord does have an option to leave servers."
            )
        )

    if target == bot_user:
        raise UserFeedbackError(
            custom_message=(
                "I can't ban myself from the server. "
                "If you don't want me here, use the leave command instead."
            )
        )

    if target.guild.owner == target:
        raise HierarchyException(custom_message="You can't ban the owner of a guild.")

    if not mod.guild.owner == mod:
        if target.top_role == mod.top_role:
            raise HierarchyException(
                custom_message="You can't ban someone with the same top role as you."
            )

        if target.top_role > mod.top_role:
            raise HierarchyException(
                custom_message="You can't ban someone with a higher top role than you."
            )

    if not bot_user.guild.owner == bot_user:
        if target.top_role == bot_user.top_role:
            raise HierarchyException(
                custom_message="I can't ban someone with the same top role as me."
            )

        if target.top_role >= bot_user.top_role:
            raise HierarchyException(
                custom_message="I can't ban someone with a higher top role than me."
            )


def owner_or_perms(**perms):

    return commands.check_any(
        commands.is_owner(), commands.has_guild_permissions(**perms)
    )


class Mod(commands.Cog):
    """ Some basic mod tools """

    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot

    @owner_or_perms(kick_members=True)
    @commands.bot_has_guild_permissions(kick_members=True)
    @commands.guild_only()
    @commands.command(name="kick")
    async def kick_commnand(
        self, ctx: SalamanderContext, who: discord.Member, *, reason: str = ""
    ):
        """ Kick a member without removing messages """

        kick_sanity_check(bot_user=ctx.me, mod=ctx.author, target=who)
        await who.kick(
            reacon=f"User kicked by command. (Authorizing mod: {ctx.author}({ctx.author.id})"
        )
        self.bot.modlog.member_kick(mod=ctx.author, target=who, reason=reason)

    @owner_or_perms(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    @commands.command(name="ban")
    async def ban_command(
        self,
        ctx: SalamanderContext,
        who: Union[discord.Member, int],  # TODO: handle this better
        *,
        reason: str = "",
    ):
        """ Ban a member without removing messages """

        if isinstance(who, discord.Member):
            ban_sanity_check(bot_user=ctx.me, mod=ctx.author, target=who)
            await who.ban(
                reason=f"User banned by command. (Authorizing mod: {ctx.author}({ctx.author.id})"
            )
            self.bot.modlog.member_ban(mod=ctx.author, target=who, reason=reason)
        else:
            await ctx.guild.ban(
                discord.Object(id=who), reason=reason, delete_message_days=0
            )
            self.bot.modlog.user_ban(mod=ctx.author, target_id=who, reason=reason)

    # TODO: more commands / ban options
