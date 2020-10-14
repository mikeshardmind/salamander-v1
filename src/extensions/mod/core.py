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

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

import discord
from discord.ext import commands

from ...bot import HierarchyException, Salamander, SalamanderContext, UserFeedbackError
from ...checks import admin_or_perms, mod_or_perms
from ...utils import format_list
from ...utils.converters import MemberOrID, TimedeltaConverter

INSERT_OR_IGNORE_GUILD = """
INSERT INTO guild_settings (guild_id) VALUES (?)
ON CONFLICT (guild_id) DO NOTHING
"""

GET_MUTE_ROLE = """
SELECT mute_role FROM guild_settings WHERE guild_id = ?
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


class Mod(commands.Cog):
    """ Some basic mod tools """

    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot
        self._mute_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._bgloop = asyncio.create_task(self.background_loop())

    def cog_unload(self):
        self._bgloop.cancel()

    @mod_or_perms(kick_members=True)
    @commands.bot_has_guild_permissions(kick_members=True)
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

    @mod_or_perms(ban_members=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @commands.command(name="ban")
    async def ban_command(
        self, ctx: SalamanderContext, who: MemberOrID, *, reason: str = "",
    ):
        """ Ban a member without removing messages """

        if member := who.member:

            ban_sanity_check(bot_user=ctx.me, mod=ctx.author, target=member)
            await member.ban(
                reason=f"User banned by command. (Authorizing mod: {ctx.author}({ctx.author.id})",
                delete_message_days=0,
            )

        else:
            drsn = (
                f"User not in guild banned by command. "
                f"(Authorizing mod: {ctx.author}({ctx.author.id})"
            )
            await ctx.guild.ban(
                discord.Object(who.id), reason=drsn, delete_message_days=0
            )

        self.bot.modlog.member_ban(mod=ctx.author, target=member, reason=reason)

    # TODO: more commands / ban options

    async def mute_user_logic(
        self,
        *,
        mod: discord.Member,
        target: discord.Member,
        reason: str,
        audit_reason: str,
        expiration: Optional[datetime] = None,
    ):
        guild = mod.guild
        async with self._mute_locks[guild.id]:

            cursor = self.bot._conn.cursor()
            params = (guild.id,)
            cursor.execute(INSERT_OR_IGNORE_GUILD, params)

            row = cursor.execute(GET_MUTE_ROLE, params).fetchone()

            mute_role_id = next(iter(row), None) if row is not None else None

            if mute_role_id is None:
                raise UserFeedbackError(
                    custom_message="No mute role has been configured."
                )

            mute_role = guild.get_role(mute_role_id)
            if mute_role is None:
                raise UserFeedbackError(
                    custom_message="The mute role for this server appears to have been deleted."
                )

            mute_sanity_check(bot_user=guild.me, mod=mod, target=target)

            removed_role_ids = []
            intended_state = [mute_role]
            for r in target.roles:
                if r.managed or r.is_default():
                    intended_state.append(r)
                else:
                    removed_role_ids.append(r.id)

            intended_state.sort()

            if intended_state != target.roles:
                await target.edit(roles=intended_state, reason=audit_reason)

            self.bot.modlog.member_muted(mod=mod, target=target, reason=reason)

            with self.bot._conn:
                expirestamp = expiration.isoformat() if expiration is not None else None
                cursor.execute(
                    """
                    INSERT INTO guild_mutes (guild_id, user_id, mute_role_used, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET
                        mute_role_used=excluded.mute_role_used,
                        expires_at=excluded.expires_at
                    """,
                    (guild.id, target.id, mute_role_id, expirestamp),
                )
                cursor.executemany(
                    """
                    INSERT INTO guild_mute_removed_roles (guild_id, user_id, removed_role_id)
                    VALUES (?,?,?)
                    ON CONFLICT (guild_id, user_id, removed_role_id)
                    DO NOTHING
                    """,
                    tuple((guild.id, target.id, rid) for rid in removed_role_ids),
                )

    async def background_loop(self):

        cursor = self.bot._conn.cursor()

        while True:

            for guild_id, user_id in cursor.execute(
                """
                SELECT guild_id, user_id FROM guild_mutes
                WHERE expires_at IS NOT NULL and expires_at < CURRENT_TIMESTAMP
                """
            ):
                asyncio.create_task(
                    self.unmute_logic(guild_id, user_id, "", "Tempmute expiration")
                )

            await asyncio.sleep(30)

    @mod_or_perms(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
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

    @mod_or_perms(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @commands.command(name="tempmute")
    async def temp_mute_command(
        self,
        ctx: SalamanderContext,
        who: discord.Member,
        duration: TimedeltaConverter,
        *,
        reason: str = "",
    ):
        """ Mute a user using the configure mute role for a duration. """

        audit_reason = (
            f"User muted for {duration} by command. (Mod: {ctx.author}({ctx.author.id})"
        )

        expiration = datetime.utcnow().replace(tzinfo=timezone.utc) + duration.delta

        await self.mute_user_logic(
            mod=ctx.author,
            target=who,
            reason=reason,
            audit_reason=audit_reason,
            expiration=expiration,
        )
        await ctx.send(f"User Muted for {duration}")

    @mod_or_perms(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @commands.command(name="unmute")
    async def basic_unmute_command(
        self, ctx: SalamanderContext, who: discord.Member, *, reason: str = "",
    ):
        """ Unmute a user """

        audit_reason = f"User unmuted by command. (Mod: {ctx.author}({ctx.author.id})"
        cant_restore = await self.unmute_logic(
            ctx.guild.id, who.id, reason, audit_reason, mod=ctx.author
        )

        if cant_restore:
            r_s = format_list([r.name for r in cant_restore])
            await ctx.send(f"User unmuted. A few roles could not be restored: {r_s}")
        else:
            await ctx.send("User unmuted.")

    async def unmute_logic(
        self,
        guild_id: int,
        member_id: int,
        reason: str,
        audit_reason: str,
        *,
        mod: Optional[discord.Member] = None,
    ) -> List[discord.Role]:

        cursor = self.bot._conn.cursor()
        params = (guild_id,)
        cursor.execute(INSERT_OR_IGNORE_GUILD, params)

        row = cursor.execute(GET_MUTE_ROLE, params).fetchone()
        mute_role_id = next(iter(row), None) if row is not None else None

        if mute_role_id is None:
            raise UserFeedbackError(custom_message="No mute role has been configured.")

        guild = self.bot.get_guild(guild_id)
        if not guild:
            raise RuntimeError()  # only possible from bg loop

        mute_role = guild.get_role(mute_role_id)
        if mute_role is None:
            raise UserFeedbackError(
                custom_message="The mute role for this server appears to have been deleted."
            )

        who = guild.get_member(member_id)

        member_params = (guild_id, member_id)

        if who is None:
            async with self._mute_locks[guild_id]:
                cursor.execute(
                    """
                    DELETE FROM guild_mutes WHERE guild_id = ? AND user_id = ?
                    """,
                    member_params,
                )
            raise UserFeedbackError(custom_message="User is no longer in this server.")

        elif mute_role not in who.roles:
            async with self._mute_locks[guild_id]:
                cursor.execute(
                    """
                    DELETE FROM guild_mutes WHERE guild_id = ? AND user_id = ?
                    """,
                    member_params,
                )
                # Prevent mute dodge applying if someone manually unmuted then this command was run
                raise UserFeedbackError(
                    custom_message="User does not appear to be muted."
                )

        async with self._mute_locks[guild_id]:
            if (
                cursor.execute(
                    """
                    SELECT 1
                    FROM guild_mutes
                    WHERE guild_id=? AND user_id=?
                    """,
                    member_params,
                ).fetchone()
                is None
            ):
                raise UserFeedbackError(
                    custom_message="User was not muted using this bot (not unmuting)."
                )

            # Above is needed since it is possible to mute someone *without* removing any roles

            to_restore = [
                role_id
                for (role_id,) in cursor.execute(
                    """
                    SELECT removed_role_id
                    FROM guild_mute_removed_roles
                    WHERE guild_id=? AND user_id=?
                    """,
                    member_params,
                )
            ]

            intended_state = [r for r in who.roles if r.id != mute_role_id]
            cant_add = []
            for role_id in to_restore:
                role = guild.get_role(role_id)
                if role:
                    if role.managed or role >= guild.me.top_role:
                        cant_add.append(role)
                    else:
                        intended_state.append(role)

            intended_state.sort()

            if intended_state != who.roles:
                await who.edit(roles=intended_state, reason=audit_reason)

            if mod:
                self.bot.modlog.member_unmuted(mod=mod, target=who, reason=reason)

            cursor.execute(
                """
                DELETE FROM guild_mutes WHERE guild_id = ? AND user_id = ?
                """,
                member_params,
            )
            return cant_add

    @admin_or_perms(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @commands.command(name="setmuterole", ignore_extra=False)
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
        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id, mute_role) VALUES (?,?)
            ON CONFLICT (guild_id) DO UPDATE SET
                mute_role=excluded.mute_role
            """,
            (ctx.guild.id, role.id),
        )
        await ctx.send("Mute role set.")

    @set_muterole_command.error
    async def mute_role_error(self, ctx, exc):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send(
                "You've given me what appears to be more than 1 role. "
                "If your role name has spaces in it, quote it."
            )

    @commands.Cog.listener("on_member_join")
    async def mute_dodge_check(self, member: discord.Member):

        cursor = self.bot._conn.cursor()

        guild = member.guild

        if not guild.me.guild_permissions.manage_roles:
            return  # Can't do anything anyhow

        async with self._mute_locks[guild.id]:
            if (
                cursor.execute(
                    """
                    SELECT 1
                    FROM guild_mutes
                    WHERE guild_id=? AND user_id=?
                    """,
                    (guild.id, member.id),
                ).fetchone()
                is None
            ):
                return

            # check that we have a mute role

            row = cursor.execute(GET_MUTE_ROLE, (guild.id,)).fetchone()
            if row is None:
                return

            (role_id,) = row

            role = guild.get_role(role_id)
            if role is None:
                return

            if role > guild.me.top_role and guild.owner != guild.me:
                return

            # Prevents unexpected granting of roles to mute dodgers
            cursor.execute(
                """
                DELETE FROM guild_mute_removed_roles
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild.id, member.id),
            )

            await member.add_roles(role, reason="Detected mute dodge on rejoin")
