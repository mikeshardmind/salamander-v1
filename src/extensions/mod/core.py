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

INSERT_OR_IGNORE_GUILD = """
INSERT INTO guild_settings (guild_id) VALUES (?)
ON CONFLICT (guild_id) DO NOTHING
"""

CREATE_MUTE = """
INSERT_INTO guild_mutes (guild_id, user_id, expires_at, mute_role_used, removed_roles)
VALUES (
    :guild_id,
    :user_id,
    :expires_at,
    :mute_role_used,
    :removed_roles
)
"""

GET_DETAILS_FOR_UNMUTE = """
SELECT removed_roles FROM guild_mutes WHERE guild_id = ? AND user_id = ?
"""

GET_MUTE_ROLE = """
SELECT mute_role FROM guild_settings WHERE guild_id = ?
"""

REMOVE_MUTE = """
DELETE FROM guild_mutes WHERE guild_id = ? AND user_id = ?
"""


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
        raise HierarchyException(custom_message="You can't kick the owner of a server.")

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
        raise HierarchyException(custom_message="You can't ban the owner of a server.")

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


def mute_sanity_check(
    bot_user: discord.Member, mod: discord.Member, target: discord.Member,
):

    if target == mod:
        raise UserFeedbackError(custom_message=("You can't mute yourself (yet.)"))

    if target == bot_user:
        raise UserFeedbackError(
            custom_message=(
                "I can't mute myself. "
                "If you don't want me here, use the leave command instead."
            )
        )

    if target.guild.owner == target:
        raise HierarchyException(custom_message="You can't mute the owner of a guild.")

    if not mod.guild.owner == mod:
        if target.top_role == mod.top_role:
            raise HierarchyException(
                custom_message="You can't mute someone with the same top role as you."
            )

        if target.top_role > mod.top_role:
            raise HierarchyException(
                custom_message="You can't mute someone with a higher top role than you."
            )

    if not bot_user.guild.owner == bot_user:
        if target.top_role == bot_user.top_role:
            raise HierarchyException(
                custom_message="I can't mute someone with the same top role as me."
            )

        if target.top_role >= bot_user.top_role:
            raise HierarchyException(
                custom_message="I can't mute someone with a higher top role than me."
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
        else:  # TODO: Verify: Is this guaranteed to convert to a member if the ID is a member? --Liz
            await ctx.guild.ban(
                discord.Object(id=who), reason=reason, delete_message_days=0
            )
            self.bot.modlog.user_ban(mod=ctx.author, target_id=who, reason=reason)

    # TODO: more commands / ban options

    @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
    @owner_or_perms(manage_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    @commands.command(name="mute")
    async def basic_mute_command(
        self, ctx: SalamanderContext, who: discord.Member, *, reason: str = "",
    ):
        """ Mute a user using the configure mute role """

        cursor = ctx.bot._conn.cursor()
        params = (ctx.guild.id,)
        cursor.execute(INSERT_OR_IGNORE_GUILD, params)
        (mute_role_id,) = cursor.execute(GET_MUTE_ROLE, params)

        if mute_role_id is None:
            raise UserFeedbackError("No mute role has been configured.")

        mute_role = ctx.guild.get_role(mute_role_id)
        if mute_role is None:
            raise UserFeedbackError(
                "The mute role for this server appears to have been deleted."
            )

        if mute_role in who.roles:
            raise UserFeedbackError("User is already muted.")

        mute_sanity_check(bot_user=ctx.me, mod=ctx.author, target=who)

        removed_role_ids = []
        intended_state = [mute_role]
        for r in who.roles:
            if r.managed or r.is_default():
                intended_state.append(r)
            else:
                removed_role_ids.append(r.id)

        await who.edit(
            roles=intended_state,
            reason=f"User muted by command. (Authorizing mod: {ctx.author}({ctx.author.id})",
        )

        self.bot.modlog.mute_member(mod=ctx.author, target=who, reason=reason)

        cursor.execute(
            CREATE_MUTE,
            dict(
                guild_id=ctx.guild.id,
                user_id=who.id,
                mute_role_used=mute_role_id,
                removed_roles=msgpack.packb(removed_role_ids),
            ),
        )

    @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
    @owner_or_perms(manage_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    @commands.command(name="unmute")
    async def basic_unmute_command(
        self, ctx: SalamanderContext, who: discord.Member, *, reason: str = "",
    ):
        """ Unmute a user """

        cursor = ctx.bot._conn.cursor()
        params = (ctx.guild.id,)
        cursor.execute(INSERT_OR_IGNORE_GUILD, params)
        (mute_role_id,) = cursor.execute(GET_MUTE_ROLE, params)

        if mute_role_id is None:
            raise UserFeedbackError("No mute role has been configured.")

        mute_role = ctx.guild.get_role(mute_role_id)
        if mute_role is None:
            raise UserFeedbackError(
                "The mute role for this server appears to have been deleted."
            )

        if mute_role not in who.roles:
            raise UserFeedbackError("User does not appear to be muted")

        params = (ctx.guild.id, who.id)
        data = next(cursor.execute(GET_DETAILS_FOR_UNMUTE, params), None,)

        if data is None:
            raise UserFeedbackError("User was not muted using this bot (not unmuting).")

        role_ids = msgpack.unpackb(data, use_list=False)

        intended_state = [r for r in who.roles if r.id != mute_role_id]
        cant_add = []
        for role_id in role_ids:
            role = ctx.guild.get_role(role_id)
            if role:
                if r.managed or r >= ctx.guild.me.top_role:
                    cant_add.append(r)
                else:
                    intended_state.append(role)

        await who.edit(
            roles=intended_state,
            reason=f"User unmuted by command. (Authorizing mod: {ctx.author}({ctx.author.id})",
        )

        self.bot.modlog.unmute_member(mod=ctx.author, target=who, reason=reason)

        cursor.execute(REMOVE_MUTE, params)

        if cant_add:
            r_s = ", ".join(r.name for r in cant_add)
            await ctx.send(f"User unmuted, but I could not restore these roles: {rs}")
        else:
            await ctx.send(f"User unmuted.")
