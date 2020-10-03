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

import contextlib
from typing import Optional, Union

import discord
import msgpack
from discord.ext import commands

from ...bot import HierarchyException, Salamander, SalamanderContext, UserFeedbackError
from ...utils import format_list

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
ON CONFLICT (guild_id, user_id) DO UPDATE SET
    expires_at=excluded.expires_at,
    mute_role_used=excluded.mute_role_used,
    removed_roles=excluded.removed_roles,
    expires_at=excluded.expires_at,
"""

GET_DETAILS_FOR_UNMUTE = """
SELECT removed_roles FROM guild_mutes WHERE guild_id = ? AND user_id = ?
"""

GET_MUTE_EXPIRATION = """
SELECT expires_at FROM guild_mutes WHERE guild_id = ? AND user_id = ?
"""

GET_MUTE_ROLE = """
SELECT mute_role FROM guild_settings WHERE guild_id = ?
"""

SET_MUTE_ROLE = """
INSERT INTO guild_settings (guild_id, mute_role) VALUES (?,?)
ON CONFLICT (guild_id) DO UPDATE SET
    mute_role=excluded.mute_role
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

    async def mute_user_logic(
        self,
        *,
        mod: discord.Member,
        target: discord.Member,
        reason: str,
        audit_reason: str,
        expiration: Optional[str] = None,
    ):

        guild = mod.guild
        cursor = self.bot._conn.cursor()
        params = (guild.id,)
        cursor.execute(INSERT_OR_IGNORE_GUILD, params)
        (mute_role_id,) = cursor.execute(GET_MUTE_ROLE, params)

        if mute_role_id is None:
            raise UserFeedbackError(custom_message="No mute role has been configured.")

        mute_role = guild.get_role(mute_role_id)
        if mute_role is None:
            raise UserFeedbackError(
                custom_message="The mute role for this server appears to have been deleted."
            )

        if mute_role in target.roles:
            raise UserFeedbackError(custom_message="User is already muted.")

        mute_sanity_check(bot_user=guild.me, mod=mod, target=target)

        removed_role_ids = []
        intended_state = [mute_role]
        for r in target.roles:
            if r.managed or r.is_default():
                intended_state.append(r)
            else:
                removed_role_ids.append(r.id)

        await target.edit(roles=intended_state, reason=audit_reason)

        self.bot.modlog.member_muted(mod=mod, target=target, reason=reason)

        cursor.execute(
            CREATE_MUTE,
            dict(
                guild_id=guild.id,
                user_id=target.id,
                mute_role_used=mute_role_id,
                removed_roles=msgpack.packb(removed_role_ids),
                expires_at=expiration,
            ),
        )

    @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
    @owner_or_perms(manage_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    @commands.command(name="mute")
    async def basic_mute_command(
        self, ctx: SalamanderContext, who: discord.Member, *, reason: str = "",
    ):
        """ Mute a user using the configure mute role """

        audit_reason = f"User muted by command. (Mod: {ctx.author}({ctx.author.id})"

        await self.mute_user_logic(
            mod=ctx.author, target=who, reason=reason, audit_reason=audit_reason
        )
        await ctx.send("User Muted")

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
            raise UserFeedbackError(custom_message="No mute role has been configured.")

        mute_role = ctx.guild.get_role(mute_role_id)
        if mute_role is None:
            raise UserFeedbackError(
                custom_message="The mute role for this server appears to have been deleted."
            )

        if mute_role not in who.roles:
            raise UserFeedbackError(custom_message="User does not appear to be muted")

        data = next(
            cursor.execute(GET_DETAILS_FOR_UNMUTE, (ctx.guild.id, who.id)), None
        )

        if data is None:
            raise UserFeedbackError(
                custom_message="User was not muted using this bot (not unmuting)."
            )

        role_ids = msgpack.unpackb(data, use_list=False)

        intended_state = [r for r in who.roles if r.id != mute_role_id]
        cant_add = []
        for role_id in role_ids:
            role = ctx.guild.get_role(role_id)
            if role:
                if role.managed or role >= ctx.guild.me.top_role:
                    cant_add.append(role)
                else:
                    intended_state.append(role)

        audit_reason = f"User unmuted by command. (Mod: {ctx.author}({ctx.author.id})"

        await who.edit(roles=intended_state, reason=audit_reason)

        self.bot.modlog.member_unmuted(mod=ctx.author, target=who, reason=reason)
        cursor.execute(REMOVE_MUTE, params)

        if cant_add:
            r_s = format_list([r.name for r in cant_add])
            await ctx.send(f"User unmuted. A few roles could not be restored: {r_s}")
        else:
            await ctx.send("User unmuted.")

    @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
    @owner_or_perms(manage_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    @commands.command(name="setmuterole")
    async def set_muterole_command(self, ctx: SalamanderContext, role: discord.Role):
        """ Set the mute role for the server """

        if role >= ctx.me.top_role and ctx.guild.owner != ctx.me:
            raise UserFeedbackError(
                custom_message="I won't be able to use that mute role. "
                "Try placing the mute role as the lowest role and ensure it has no permissions"
            )

        if role >= ctx.author.top_role and ctx.guild.owner != ctx.author:
            raise UserFeedbackError(
                custom_message="I can't let you set a mute role above your own role."
            )

        if role.permissions > ctx.author.guild_permissions:
            raise UserFeedbackError(
                custom_message="I can't let you set a mute role with permissions you don't have."
            )

        if role.managed:
            raise UserFeedbackError(
                custom_message="This is a role which is managed by an integration. I cannot use it for mutes."
            )

        if role.permissions.value != 0:
            prompt = (
                "We recommend mute roles have no permissions. "
                "This one has at least one permission value set."
                "\nDo you want to use this role anyway? (yes/no)"
            )

            response = await ctx.prompt(prompt, options=("yes", "no"), timeout=30)
            if response == "no":
                await ctx.send("Okay, not setting the role.")
                return

        cursor = self.bot._conn.cursor()
        cursor.execute(SET_MUTE_ROLE, (ctx.guild.id, role.id))
        await ctx.send("Mute role set.")

    @commands.Cog.listener("on_member_join")
    async def mute_dodge_check(self, member: discord.Member):

        with contextlib.suppress(StopIteration, UserFeedbackError):
            cursor = self.bot._conn.cursor()
            (expiration,) = next(
                cursor.execute(GET_MUTE_EXPIRATION, (member.guild.id, member.id))
            )

            # TODO: don't remute if it's a timed mute that's expired (No timed mute support yet)

            rsn = "Detected mute dodging."
            await self.mute_user_logic(
                mod=member.guild.me,
                target=member,
                reason=rsn,
                audit_reason=rsn,
                expiration=expiration,
            )
