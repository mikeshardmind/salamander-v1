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

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, MutableMapping, Optional, Union
from weakref import WeakValueDictionary

import discord
from discord.ext import commands

from ...bot import HierarchyException, Salamander, SalamanderContext, UserFeedbackError
from ...checks import admin_or_perms, mod_or_perms
from ...utils import StrictMemberConverter, TimedeltaConverter, embed_from_member, format_list, humanize_seconds
from .converters import MultiBanConverter, SearchBanConverter

log = logging.getLogger("salamander.extensions.mod")


INSERT_OR_IGNORE_GUILD = """
INSERT INTO guild_settings (guild_id) VALUES (?)
ON CONFLICT (guild_id) DO NOTHING
"""

GET_MUTE_ROLE = """
SELECT mute_role FROM guild_settings WHERE guild_id = ?
"""


def kick_soundness_check(bot_user: discord.Member, mod: discord.Member, target: discord.Member):

    if target == mod:
        raise UserFeedbackError(
            custom_message=("You can't kick yourself, " "but Discord does have an option to leave servers.")
        )

    if target == bot_user:
        raise UserFeedbackError(
            custom_message=(
                "I can't kick myself from the server. " "If you don't want me here, use the leave command instead."
            )
        )

    if target.guild.owner == target:
        raise HierarchyException(custom_message="You can't kick the owner of a server.")

    if mod.guild.owner != mod:
        if target.top_role == mod.top_role:
            raise HierarchyException(custom_message="You can't kick someone with the same top role as you.")

        if target.top_role > mod.top_role:
            raise HierarchyException(custom_message="You can't kick someone with a higher top role than you.")

    if bot_user.guild.owner != bot_user:
        if target.top_role == bot_user.top_role:
            raise HierarchyException(custom_message="I can't kick someone with the same top role as me.")

        if target.top_role >= bot_user.top_role:
            raise HierarchyException(custom_message="I can't kick someone with a higher top role than me.")


def ban_soundness_check(
    bot_user: discord.Member,
    mod: discord.Member,
    target: discord.Member,
):

    if target == mod:
        raise UserFeedbackError(
            custom_message=("You can't ban yourself, " "but Discord does have an option to leave servers.")
        )

    if target == bot_user:
        raise UserFeedbackError(
            custom_message=(
                "I can't ban myself from the server. " "If you don't want me here, use the leave command instead."
            )
        )

    if target.guild.owner == target:
        raise HierarchyException(custom_message="You can't ban the owner of a server.")

    if mod.guild.owner != mod:
        if target.top_role == mod.top_role:
            raise HierarchyException(custom_message="You can't ban someone with the same top role as you.")

        if target.top_role > mod.top_role:
            raise HierarchyException(custom_message="You can't ban someone with a higher top role than you.")

    if bot_user.guild.owner != bot_user:
        if target.top_role == bot_user.top_role:
            raise HierarchyException(custom_message="I can't ban someone with the same top role as me.")

        if target.top_role >= bot_user.top_role:
            raise HierarchyException(custom_message="I can't ban someone with a higher top role than me.")


def mute_soundness_check(
    bot_user: discord.Member,
    mod: discord.Member,
    target: discord.Member,
):

    if target == mod:
        raise UserFeedbackError(custom_message=("You can't mute yourself (yet.)"))

    if target == bot_user:
        raise UserFeedbackError(
            custom_message=("I can't mute myself. " "If you don't want me here, use the leave command instead.")
        )

    if target.guild.owner == target:
        raise HierarchyException(custom_message="You can't mute the owner of a guild.")

    if mod.guild.owner != mod:
        if target.top_role == mod.top_role:
            raise HierarchyException(custom_message="You can't mute someone with the same top role as you.")

        if target.top_role > mod.top_role:
            raise HierarchyException(custom_message="You can't mute someone with a higher top role than you.")

    if bot_user.guild.owner != bot_user:
        if target.top_role == bot_user.top_role:
            raise HierarchyException(custom_message="I can't mute someone with the same top role as me.")

        if target.top_role >= bot_user.top_role:
            raise HierarchyException(custom_message="I can't mute someone with a higher top role than me.")


class Mod(commands.Cog):
    """ Some basic mod tools """

    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot
        self._mute_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._bgloop = asyncio.create_task(self.background_loop())
        self.antispam: Dict[int, commands.cooldowns.CooldownMapping] = {}
        self._ban_concurrency: MutableMapping[int, asyncio.Lock] = WeakValueDictionary()

    def cog_unload(self):
        self._bgloop.cancel()

    @commands.guild_only()
    @commands.group()
    async def antimentionspam(self, ctx: SalamanderContext):
        """
        Configuration settings for AntiMentionSpam
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @admin_or_perms(manage_guild=True)
    @antimentionspam.command(name="max")
    async def set_max_mentions(self, ctx: SalamanderContext, number: int):
        """
        Sets the maximum number of mentions allowed in a message.
        A setting of 0 disables this check.
        """
        cursor = self.bot._conn.cursor()

        cursor.execute(
            """
            INSERT INTO guild_settings(guild_id) VALUES (:guild_id)
            ON CONFLICT (guild_id) DO NOTHING;
            INSERT INTO antimentionspam_settings (guild_id, max_mentions_single)
            VALUES (:guild_id, :number)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                max_mentions_single=excluded.max_mentions_single;
            """,
            {"guild_id": ctx.guild.id, "number": number},
        )

        message = f"Max mentions per message set to {number}." if number > 0 else "Mention filtering has been disabled."
        await ctx.send(message)

    @admin_or_perms(manage_guild=True)
    @antimentionspam.command(name="maxinterval")
    async def set_max_interval_mentions(self, ctx: SalamanderContext, number: int, seconds: int):
        """
        Sets the maximum number of mentions allowed in a time period.
        Setting either to 0 will disable this check.
        """
        if number == 0 or seconds == 0:
            number = seconds = 0

        cursor = self.bot._conn.cursor()

        cursor.execute(
            """
            INSERT INTO guild_settings(guild_id) VALUES (:guild_id)
            ON CONFLICT (guild_id) DO NOTHING;
            INSERT INTO antimentionspam_settings
                (guild_id, max_mentions_interval, interval_length)
            VALUES (:guild_id, :number, :seconds)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                max_mentions_interval=excluded.max_mentions_interval,
                interval_length=excluded.interval_length;
            """,
            {"guild_id": ctx.guild.id, "number": number, "seconds": seconds},
        )

        message = (
            f"Max mentions set to {number} per {seconds} seconds."
            if number > 0 or seconds > 0
            else "Mention interval filtering has been disabled."
        )
        self.antispam[ctx.guild.id] = commands.CooldownMapping.from_cooldown(
            number, seconds, commands.BucketType.member
        )
        await ctx.send(message)

    @admin_or_perms(manage_guild=True)
    @antimentionspam.command(name="autobantoggle")
    async def autobantoggle(self, ctx: SalamanderContext, enabled: bool = None):
        """
        Toggle automatic ban for spam (default off)
        """
        cursor = self.bot._conn.cursor()

        if enabled is None:
            (enabled,) = cursor.execute(
                """
                INSERT INTO guild_settings(guild_id) VALUES (:guild_id)
                ON CONFLICT (guild_id) DO NOTHING;
                INSERT INTO antimentionspam_settings(guild_id) VALUES (:guild_id)
                ON CONFLICT (guild_id) DO NOTHING;
                UPDATE antimentionspam_settings
                SET ban=NOT ban
                    WHERE guild_id=:guild_id
                RETURNING ban;
                """,
                {"guild_id": ctx.guild.id},
            ).fetchone()
        else:
            cursor.execute(
                """
                INSERT INTO guild_settings(guild_id) VALUES (:guild_id)
                ON CONFLICT (guild_id) DO NOTHING;
                INSERT INTO antimentionspam_settings(guild_id, ban)
                    VALUES (:guild_id, :ban)
                ON CONFLICT (guild_id)
                DO UPDATE SET ban=excluded.ban;
                """,
                {"guild_id": ctx.guild.id, "ban": enabled},
            )

        await ctx.send(f"Autoban mention spammers: {enabled}")

    @admin_or_perms(manage_guild=True)
    @antimentionspam.command(name="warnmsg")
    async def warnmessage(self, ctx: SalamanderContext, *, msg: str):
        """
        Sets the warn message. Not providing one turns it off.
        """
        cursor = self.bot._conn.cursor()

        cursor.execute(
            """
            INSERT INTO guild_settings(guild_id) VALUES (:guild_id)
            ON CONFLICT (guild_id) DO NOTHING;
            INSERT INTO antimentionspam_settings(guild_id, warn_message)
                VALUES (:guild_id, :msg)
            ON CONFLICT (guild_id)
            DO UPDATE SET warn_message=excluded.warn_message;
            """,
            {"guild_id": ctx.guild.id, "msg": msg},
        )

        await ctx.send("Warn message set." if msg else "Warn message disabled.")

    @admin_or_perms(manage_guild=True)
    @antimentionspam.command(name="singlebantoggle")
    async def singlebantog(self, ctx: SalamanderContext, enabled: bool = None):
        """
        Sets if single message limits allow a ban
        Default: False (interval threshold exceeding is required)
        """
        cursor = self.bot._conn.cursor()

        if enabled is None:
            (enabled,) = cursor.execute(
                """
                INSERT INTO guild_settings(guild_id) VALUES (:guild_id)
                ON CONFLICT (guild_id) DO NOTHING;
                INSERT INTO antimentionspam_settings(guild_id) VALUES (:guild_id)
                ON CONFLICT (guild_id) DO NOTHING;
                UPDATE antimentionspam_settings
                SET ban_single=NOT ban_single
                    WHERE guild_id=:guild_id
                RETURNING ban_single;
                """,
                {"guild_id": ctx.guild.id},
            ).fetchone()
        else:
            cursor.execute(
                """
                INSERT INTO guild_settings(guild_id) VALUES (:guild_id)
                ON CONFLICT (guild_id) DO NOTHING;
                INSERT INTO antimentionspam_settings(guild_id, ban_single)
                    VALUES (:guild_id, :ban)
                ON CONFLICT (guild_id)
                DO UPDATE SET ban_single=excluded.ban_single;
                """,
                {"guild_id": ctx.guild.id, "ban": enabled},
            )

        await ctx.send(f"Ban from single message settings: {enabled}")

    @admin_or_perms(manage_guild=True)
    @antimentionspam.command(name="mutetoggle")
    async def mute_toggle(self, ctx: SalamanderContext, enabled: bool = None):
        """
        Sets if a mute should be applied on exceeding limits set.
        """

        cursor = self.bot._conn.cursor()

        if enabled is None:
            (enabled,) = cursor.execute(
                """
                INSERT INTO guild_settings(guild_id) VALUES (:guild_id)
                ON CONFLICT (guild_id) DO NOTHING;
                INSERT INTO antimentionspam_settings(guild_id) VALUES (:guild_id)
                ON CONFLICT (guild_id) DO NOTHING;
                UPDATE antimentionspam_settings
                SET mute=NOT mute
                    WHERE guild_id=:guild_id
                RETURNING mute;
                """,
                {"guild_id": ctx.guild.id},
            ).fetchone()
        else:
            cursor.execute(
                """
                INSERT INTO guild_settings(guild_id) VALUES (:guild_id)
                ON CONFLICT (guild_id) DO NOTHING;
                INSERT INTO antimentionspam_settings(guild_id, mute)
                    VALUES (:guild_id, :ban)
                ON CONFLICT (guild_id)
                DO UPDATE SET mute=excluded.mute;
                """,
                {"guild_id": ctx.guild.id, "mute": enabled},
            )

        message = (
            "Users will be muted when exceeding set limits."
            if enabled
            else "Users will not be muted when exceeding set limits."
        )

        await ctx.send(message)

    @mod_or_perms(kick_members=True)
    @commands.bot_has_guild_permissions(kick_members=True)
    @commands.command(name="kick")
    async def kick_commnand(self, ctx: SalamanderContext, who: discord.Member, *, reason: str = ""):
        """ Kick a member without removing messages """

        kick_soundness_check(bot_user=ctx.me, mod=ctx.author, target=who)
        await who.kick(reacon=f"User kicked by command. (Authorizing mod: {ctx.author}({ctx.author.id})")
        self.bot.modlog.member_kick(mod=ctx.author, target=who, reason=reason)

    @mod_or_perms(ban_members=True)
    @commands.bot_has_guild_permissions(ban_members=True)
    @commands.command(name="ban")
    async def ban_command(
        self,
        ctx: SalamanderContext,
        who: StrictMemberConverter,
        *,
        reason: str = "",
    ):
        """ Ban a member without removing messages """

        if not who.id:
            raise commands.BadArgument("That wasn't a member or the ID of a user not in the server.")

        if member := who.member:

            ban_soundness_check(bot_user=ctx.me, mod=ctx.author, target=member)
            await member.ban(
                reason=f"User banned by command. (Authorizing mod: {ctx.author}({ctx.author.id})",
                delete_message_days=0,
            )
            self.bot.modlog.member_ban(mod=ctx.author, target=member, reason=reason)

        else:
            drsn = f"User not in guild banned by command. (Authorizing mod: {ctx.author}({ctx.author.id})"
            await ctx.guild.ban(discord.Object(who.id), reason=drsn, delete_message_days=0)
            self.bot.modlog.user_ban(mod=ctx.author, target_id=who.id, reason=reason)

    @mod_or_perms(ban_members=True)
    @commands.bot_has_guild_permissions(ban_members=True)
    @commands.command(name="massban")
    async def massban_command(
        self,
        ctx: SalamanderContext,
        *,
        ban_args: MultiBanConverter,
    ):
        """Ban Multiple users

        --users user_id_or_mention_one user_id_or_mention_two --reason because whatever
        """
        # change this in d.py 2.0 with shared max_concurrency
        lock = self._ban_concurrency.setdefault(ctx.guild.id, asyncio.Lock())
        async with lock:
            await self.handle_mass_or_search_ban(ctx, ban_args)

    @mod_or_perms(ban_members=True)
    @commands.bot_has_guild_permissions(ban_members=True)
    @commands.command(name="searchban")
    async def searchban_command(
        self,
        ctx: SalamanderContext,
        *,
        ban_args: SearchBanConverter,
    ):
        """Ban Multiple users

        --reason some reason
        --no-pfp
        --joined-server-within 1h
        --joined-discord-within 1d
        --username Spammer's Name
        """

        # As this was a search, let's confirm some things:

        resp = await ctx.prompt(
            f"This would ban {len(ban_args.matched_members)} members, continue? (yes/no)",
            options=("yes", "no"),
            timeout=15,
        )

        if resp != "yes":
            return

        # change this in d.py 2.0 with shared max_concurrency
        lock = self._ban_concurrency.setdefault(ctx.guild.id, asyncio.Lock())
        async with lock:
            await self.handle_mass_or_search_ban(ctx, ban_args)

    async def handle_mass_or_search_ban(self, ctx: SalamanderContext, ban_args: Union[MultiBanConverter, SearchBanConverter]):

        for member in ban_args.matched_members:
            ban_soundness_check(bot_user=ctx.me, mod=ctx.author, target=member)

        members_to_ban = len(ban_args.matched_members)
        users_to_ban = len(ban_args.unmatched_user_ids)
        total_to_ban = members_to_ban + users_to_ban

        progress: Optional[discord.Message] = None

        if total_to_ban > 50 or users_to_ban > 25:
            # Ratelimiting is worse on users no longer in the server
            progress = await ctx.send(f"This may take a while: (0/{total_to_ban} banned so far, 0s elapsed)")

        start = last = time.monotonic()

        for idx, member in enumerate(ban_args.matched_members, 1):
            try:
                await member.ban(
                    reason=f"User banned by command. (Authorizing mod: {ctx.author}({ctx.author.id})",
                    delete_message_days=0,
                )
            except discord.Forbidden:
                # Lost perms mid ban?
                raise UserFeedbackError(custom_message="Banning interrupted by losing permissions(?)")
            except discord.HTTPException as exc:
                log.exception(
                    "Unexpected HTTPException with json code %s in guild %d during memberban",
                    exc.code,
                    ctx.guild.id,
                    exc_info=exc,
                )
                banned = idx - 1
                raise UserFeedbackError(
                    custom_message=(
                        f"An unexpected error occured while banning. This error has been logged. If you continue experiencing this, report the issue."
                        f"\n\nBanned {banned} of {total_to_ban} prior to the unexpected error."
                    )
                )

            self.bot.modlog.member_ban(mod=ctx.author, target=member, reason=ban_args.reason)

            now = time.monotonic()
            if now - last > 60:
                last = now
                elapsed = humanize_seconds(int(now - start))
                if progress and (idx < members_to_ban or users_to_ban):
                    await progress.edit(
                        content=f"This may take a while: ({idx}/{total_to_ban} banned in {elapsed} so far)"
                    )

        drsn = f"User not in guild banned by command. (Authorizing mod: {ctx.author}({ctx.author.id})"
        unfound_count = 0

        for idx, user_id in enumerate(ban_args.unmatched_user_ids, 1):

            try:
                await ctx.guild.ban(discord.Object(user_id), reason=drsn, delete_message_days=0)
            except discord.NotFound:
                unfound_count += 1
                if not unfound_count % 5:
                    # Discord has additional ratelimiting that comes into play in this case and isn't documented and is a PITA.
                    # we should prevent confusing discord.py's header based ratelimit handling (Not a discord.py bug, discord is dumb about ratelimits)
                    await asyncio.sleep(3)
            except discord.Forbidden:
                # Lost perms mid ban?
                raise UserFeedbackError(custom_message="Banning interrupted by losing permissions(?)")
            except discord.HTTPException as exc:
                log.exception(
                    "HTTPException with json code %s in guild %d during ban of user not in guild.",
                    exc.code,
                    ctx.guild.id,
                    exc_info=exc,
                )
                if exc.code == 30035:
                    raise UserFeedbackError(
                        custom_message=(
                            "Discord has limits on the maximum number of people you can try and ban without them being in the server at the time of the ban. "
                            "I think this is incredibly dumb, but this limit has been hit. If you need to be able to ban more people like this, reach out to Discord."
                        )
                    )
                else:
                    banned = members_to_ban + idx - 1 - unfound_count
                    raise UserFeedbackError(
                        custom_message=(
                            f"An unexpected error occured while banning. This error has been logged. If you continue experiencing this, report the issue."
                            f"\n\nBanned {banned} of {total_to_ban} prior to the unexpected error."
                        )
                    )
            else:
                self.bot.modlog.user_ban(mod=ctx.author, target_id=user_id, reason=ban_args.reason)

                now = time.monotonic()
                if now - last > 60:
                    last = now
                    if progress and idx < users_to_ban:
                        elapsed = humanize_seconds(int(now - start))
                        banned = members_to_ban + idx - unfound_count
                        await progress.edit(
                            content=f"This may take a while: ({banned}/{total_to_ban} banned in {elapsed} so far)"
                        )

        if progress:
            await progress.delete(delay=0)  # let d.py handle this

        elapsed = humanize_seconds(int(time.monotonic() - start))

        message: str
        if unfound_count:
            message = f"Banned {total_to_ban - unfound_count}/{total_to_ban} users in {elapsed}.\n(Skipped {unfound_count} user(s) that do not appear to exist anymore)."
        else:
            message = f"Banned {total_to_ban} users in {elapsed}"

        await ctx.send(message)

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
                raise UserFeedbackError(custom_message="No mute role has been configured.")

            mute_role = guild.get_role(mute_role_id)
            if mute_role is None:
                raise UserFeedbackError(custom_message="The mute role for this server appears to have been deleted.")

            mute_soundness_check(bot_user=guild.me, mod=mod, target=target)

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
                    VALUES (?, ?, ?, DATETIME(?))
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

        async def wrapper(gid, uid):  # prevent task noise
            try:
                await self.unmute_logic(gid, uid, "", "Tempmute expiration")
            except (UserFeedbackError, RuntimeError):
                pass

        while True:

            for guild_id, user_id in cursor.execute(
                """
                SELECT guild_id, user_id FROM guild_mutes
                WHERE expires_at IS NOT NULL and DATETIME(expires_at) < CURRENT_TIMESTAMP
                """
            ):
                asyncio.create_task(wrapper(guild_id, user_id))

            await asyncio.sleep(30)

    @mod_or_perms(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @commands.command(name="mute")
    async def basic_mute_command(
        self,
        ctx: SalamanderContext,
        who: discord.Member,
        *,
        reason: str = "",
    ):
        """ Mute a user using the configure mute role """

        audit_reason = f"User muted by command. (Mod: {ctx.author}({ctx.author.id})"

        await self.mute_user_logic(mod=ctx.author, target=who, reason=reason, audit_reason=audit_reason)
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

        if duration.delta < timedelta(minutes=2):
            raise UserFeedbackError(custom_message="Temp mutes must be at least 2 minutes long")

        audit_reason = f"User muted for {duration} by command. (Mod: {ctx.author}({ctx.author.id})"

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
        self,
        ctx: SalamanderContext,
        who: discord.Member,
        *,
        reason: str = "",
    ):
        """ Unmute a user """

        audit_reason = f"User unmuted by command. (Mod: {ctx.author}({ctx.author.id})"
        cant_restore = await self.unmute_logic(ctx.guild.id, who.id, reason, audit_reason, mod=ctx.author)

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
            raise UserFeedbackError(custom_message="The mute role for this server appears to have been deleted.")

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
                raise UserFeedbackError(custom_message="User does not appear to be muted.")

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
                raise UserFeedbackError(custom_message="User was not muted using this bot (not unmuting).")

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
            raise UserFeedbackError(custom_message="I can't let you set a mute role above your own role.")

        if role.permissions > ctx.author.guild_permissions:
            raise UserFeedbackError(custom_message="I can't let you set a mute role with permissions you don't have.")

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
                "You've given me what appears to be more than 1 role. " "If your role name has spaces in it, quote it."
            )

    @commands.Cog.listener("on_member_update")
    async def member_verification_hatch(self, before: discord.Member, after: discord.Member):

        if before.pending and not after.pending:
            await self.mute_dodge_check(after)

    @commands.Cog.listener("on_member_join")
    async def mute_dodge_check(self, member: discord.Member):

        if member.pending:
            return

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

    @commands.guild_only()
    @commands.command(ignore_extra=False)
    async def userinfo(self, ctx: SalamanderContext, who: StrictMemberConverter):
        """
        Get info about a user.
        """

        if not who.member:
            if who.id:
                raise UserFeedbackError(
                    custom_message="That looks like it might be a user, but they aren't a member of this server."
                )
            raise UserFeedbackError(
                custom_message="I didn't find a matching user in this server. You can try a mention, Username#tag or their ID"
            )

        await ctx.send(embed=embed_from_member(who.member))

    @userinfo.error
    async def too_many_consistency(self, ctx, exc):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send("That didn't look like a single user to me.")

    async def mention_punish(self, message: discord.Message, settings: tuple, single_message: bool = False):
        """
        Handles the appropriate action on the author of a message based on settings.

        Parameters
        ----------
        message: discord.Message
        settings: tuple
            row from database
        single_message: bool
        """
        guild = message.guild
        target = message.author
        channel = message.channel

        _limit, _thresh, _secs, warnmsg, mute, mute_duration, ban, ban_single = settings

        mute = mute and not ban
        ban = ban and (ban_single or not single_message)

        if ban and guild.me.guild_permissions.ban_members:
            try:
                ban_soundness_check(guild.me, guild.me, target)
            except UserFeedbackError:
                pass
            else:
                await guild.ban(
                    discord.Object(id=target.id),
                    reason="Mention Spam (Automated ban)",
                )
                self.bot.modlog.member_ban(guild.me, target, "Mention Spam (Automated ban)")

        if warnmsg and channel.permissions_for(guild.me).send_messages:
            try:
                await message.channel.send(
                    f"{target.mention}: {warnmsg}",
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except discord.HTTPException:
                pass

        if mute:

            expiration = (
                datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(minutes=mute_duration)
                if mute_duration
                else None
            )

            try:
                await self.mute_user_logic(
                    mod=guild.me,
                    target=target,
                    reason="Mention Spam (Automated mute)",
                    audit_reason="Mention Spam (Automated mute)",
                    expiration=expiration,
                )
            except UserFeedbackError:
                pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        guild = message.guild
        author = message.author
        channel = message.channel

        if not message.mentions:
            return

        if (
            author.bot
            or message.guild is None
            or (author == guild.owner or author.top_role >= guild.me.top_role)
            or await self.bot.is_owner(author)
        ):
            return

        priv = self.bot.privlevel_manager
        if priv.member_is_mod(guild.id, author.id) or priv.member_is_admin(guild.id, author.id):
            return

        cursor = self.bot._conn.cursor()

        row = cursor.execute(
            """
            SELECT
                max_mentions_single,
                max_mentions_interval,
                interval_length,
                warn_message,
                mute,
                mute_duration,
                ban,
                ban_single
            FROM antimentionspam_settings WHERE guild_id=?
            """,
            (guild.id,),
        ).fetchone()

        if not row:
            return

        (
            limit,
            thresh,
            secs,
            _warn_message,
            _mute,
            _mute_duration,
            _ban,
            _ban_single,
        ) = row

        if thresh > 0 and secs > 0:
            if guild.id not in self.antispam:
                self.antispam[guild.id] = commands.CooldownMapping.from_cooldown(
                    thresh, secs, commands.BucketType.member
                )

            for _ in message.mentions:
                if self.antispam[guild.id].update_rate_limit(message):
                    await self.mention_punish(message, row)
                    break

        if len(message.mentions) > limit > 0:
            await self.mention_punish(message, row, single_message=True)

            if not channel.permissions_for(guild.me).manage_messages:
                if channel.permissions_for(guild.me).send_messages:
                    await channel.send(
                        f"Would have deleted message from {author.mention} "
                        f"for exceeding configured mention limit of: {limit}",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                return

            try:
                await message.delete()
            except discord.HTTPException:
                if channel.permissions_for(guild.me).send_messages:
                    await channel.send(
                        f"Attempt to delete message from {author.mention} "
                        f"for exceeding configured mention limit of: {limit} failed.",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
            else:
                if channel.permissions_for(guild.me).send_messages:
                    await channel.send(
                        f"Deleted message from {author.mention} " f"for exceeding configured mention limit of: {limit}",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
