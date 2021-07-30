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
import contextlib
import logging
from datetime import datetime
from typing import Sequence

import apsw
import discord
from discord.ext import commands

from ...bot import Salamander, SalamanderContext, UserFeedbackError
from ...checks import admin, mod, owner_in_guild
from ...utils import StrictMemberConverter, TimedeltaConverter, Waterfall, embed_from_member, resolve_as_roles

log = logging.getLogger("salamander.contrib_exts.activitymetadata")


class MessageMetaTrack(commands.Cog):
    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot
        self.conn = self.bot._conn
        cursor = self.conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS contrib_activitymetadata_guild_settings (
                guild_id INTEGER PRIMARY KEY NOT NULL,
                max_days INTEGER DEFAULT 89,
                enabled BOOLEAN DEFAULT false
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS contrib_activitymetadata_message_metadata (
                message_id INTEGER PRIMARY KEY NOT NULL,
                channel_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL REFERENCES contrib_activitymetadata_guild_settings(guild_id)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                user_id INTEGER NOT NULL,
                created_at TEXT AS (
                    DATETIME(
                        ((message_id >> 22) + 1420070400000) / 1000, 'unixepoch'
                    )
                ) VIRTUAL
            )
            """
        )

        self._waterfall: Waterfall[discord.Message] = Waterfall(60, 500, self.add_messages)
        self._deletions: Waterfall[int] = Waterfall(60, 500, self.delete_messages)

    @staticmethod
    def remove_tables_from_connection(conn: apsw.Connection):
        cursor = conn.cursor()
        with conn:
            cursor.execute("""DROP TABLE contrib_activitymetadata_message_metadata""")
            cursor.execute("""DROP TABLE contrib_activitymetadata_guild_settings""")

    async def add_messages(self, messages: Sequence[discord.Message]):

        with contextlib.closing(self.conn.cursor()) as cursor, self.conn:
            if messages:
                # not a full early exit, we still age out expired every minute

                tups = []
                for m in messages:
                    #  Not entirely sure the context in which this came up, let's log it in case it happens again
                    try:
                        # And we're splitting this up for a clear picture, since the AttributeError in question was on ?.id
                        mid = m.id
                        cid = m.channel.id
                        gid = m.guild.id
                        aid = m.author.id
                        tups.append((mid, cid, gid, aid))
                    except AttributeError as exc:
                        log.exception(f"Issue during message metadata logging {m!r}", exc_info=exc)

                cursor.executemany(
                    """
                    INSERT INTO contrib_activitymetadata_message_metadata(
                        message_id, channel_id, guild_id, user_id
                    )
                    SELECT ?1, ?2, ?3, ?4
                    WHERE EXISTS(
                        SELECT 1 from contrib_activitymetadata_guild_settings WHERE guild_id = ?3 AND enabled
                    )
                    ON CONFLICT (message_id) DO NOTHING
                    """,
                    tups,
                )
            cursor.execute(
                """
                DELETE FROM contrib_activitymetadata_message_metadata
                WHERE created_at < (
                    SELECT DATETIME(
                        CURRENT_TIMESTAMP, CAST(0 - max_days as TEXT) || ' days'
                    )
                    FROM contrib_activitymetadata_guild_settings
                    WHERE contrib_activitymetadata_message_metadata.guild_id = contrib_activitymetadata_guild_settings.guild_id
                )
                """
            )

    async def delete_messages(self, message_ids: Sequence[int]):

        if not message_ids:
            return

        with contextlib.closing(self.conn.cursor()) as cursor, self.conn:
            cursor.executemany(
                """
                DELETE FROM contrib_activitymetadata_message_metadata WHERE message_id = ?
                """,
                tuple((mid,) for mid in message_ids),
            )

    def cog_unload(self):
        asyncio.create_task(self._waterfall.stop())
        asyncio.create_task(self._deletions.stop())

    @commands.Cog.listener("salamander_data_deletion_guild")
    async def guild_data_drop(self, guild_id: int):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            DELETE FROM contrib_activitymetadata_guild_settings WHERE guild_id = ?
            """,
            (guild_id,),
        )  # FK handles rest

    @commands.Cog.listener("salamander_data_deletion_member")
    async def member_data_drop(self, guild_id: int, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            DELETE FROM contrib_activitymetadata_message_metadata
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )

    @commands.Cog.listener("salamander_data_deletion_user")
    async def user_data_drop(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            DELETE FROM contrib_activitymetadata_message_metadata
            WHERE user_id = ?
            """,
            (user_id,),
        )

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message):
        if message.guild and (not message.author.bot) and message.type.value == 0:
            with contextlib.suppress(RuntimeError):
                # can happen during cog unload
                self._waterfall.put(message)

    @commands.Cog.listener("on_raw_message_delete")
    async def raw_delete_handler(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id:
            with contextlib.suppress(RuntimeError):
                self._deletions.put(payload.message_id)

    @commands.Cog.listener("on_raw_bulk_message_delete")
    async def on_bulk_delete_handler(self, payload: discord.RawBulkMessageDeleteEvent):
        if payload.guild_id:
            with contextlib.suppress(RuntimeError):
                for mid in payload.message_ids:
                    self._deletions.put(mid)

    @admin()
    @commands.group(name="activitytrackset")
    async def atrackset(self, ctx: SalamanderContext):
        """Commands for managing activity tracking"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @admin()
    @atrackset.command()
    async def enable(self, ctx: SalamanderContext):
        """
        Enable tracking in this guild
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO contrib_activitymetadata_guild_settings (guild_id, enabled)
            VALUES (?, ?)
            ON CONFLICT (guild_id)
            DO UPDATE SET enabled=excluded.enabled
            """,
            (ctx.guild.id, True),
        )
        await ctx.send("Done")

    @admin()
    @atrackset.command()
    async def disable(self, ctx: SalamanderContext):
        """
        Disable tracking in this guild
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO contrib_activitymetadata_guild_settings (guild_id, enabled)
            VALUES (?, ?)
            ON CONFLICT (guild_id)
            DO UPDATE SET enabled=excluded.enabled
            """,
            (ctx.guild.id, False),
        )
        await ctx.send("Done")

    @admin()
    @atrackset.command()
    async def drop(self, ctx: SalamanderContext):
        """Drop the data for this guild"""

        if not await ctx.yes_or_no("Are you sure? (yes/no)"):
            return

        cursor = self.conn.cursor()
        cursor.execute(
            """
            DELETE from contrib_activitymetadata_message_metadata WHERE guild_id=?
            """,
            (ctx.guild.id),
        )
        await ctx.send("Done")

    @commands.max_concurrency(1, commands.BucketType.guild)
    @owner_in_guild()
    @atrackset.command(name="retro")
    async def retroactive_filler(self, ctx: SalamanderContext, period: TimedeltaConverter):
        """(very slow, use with care)"""

        await ctx.send("This may take a while, I'll let you know when it's done.")

        cutoff = ctx.message.created_at - period.delta

        try:

            for channel in ctx.guild.text_channels:
                if channel.permissions_for(ctx.guild.me).read_message_history:
                    async for message in channel.history(limit=None):
                        if message.created_at < cutoff:
                            break
                        if not message.author.bot and message.type.value == 0:
                            self._waterfall.put(message)
                        await asyncio.sleep(0.1)
                        # This is intentionally extremely slow.
                        # This should not be used frequently
                        # 10s/100msgs or ~ 1 API call every 10s

        except Exception as exc:
            log.exception(
                "Something went wrong while retroactively filling the data:",
                exc_info=exc,
            )
            raise UserFeedbackError(custom_message="Something went wrong.")

        await ctx.send(
            f"Done filling in the data {ctx.author.mention}",
            allowed_mentions=discord.AllowedMentions(users=[ctx.author]),
        )

    @retroactive_filler.error
    async def concurrency_fail(self, ctx, exc):
        if isinstance(exc, commands.MaxConcurrencyReached):
            await ctx.send("You can't be doing this while I'm already doing this.")

    @mod()
    @commands.command(name="checkactivity")
    async def check_activity(self, ctx: SalamanderContext, who: StrictMemberConverter):
        """
        Check the activity of a specific member
        """

        cursor = self.conn.cursor()

        (is_enabled,) = cursor.execute(
            """
            SELECT EXISTS(SELECT 1 FROM contrib_activitymetadata_guild_settings WHERE guild_id=? AND enabled)
            """,
            (ctx.guild.id,),
        ).fetchone()

        if not is_enabled:
            raise UserFeedbackError(custom_message="Activity tracking is not enabled for this server.")

        if not who.member:
            raise UserFeedbackError(custom_message="No matching member?")

        formatted = self.get_formatted_activity_for_member(who.member)

        await ctx.send_paged(formatted)

    @check_activity.error
    async def too_many_consistency(self, ctx, exc):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send("That didn't look like a single member to me.")

    @mod()
    @commands.group(name="activitysearch")
    async def as_group(self, ctx: SalamanderContext):
        """
        Search for members based on activity
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @commands.max_concurrency(1, commands.BucketType.guild)
    @as_group.command(name="<")
    async def less_than(self, ctx, number: int, period: TimedeltaConverter):
        """
        Search for members with fewer than a
        specified number of messages in a specified time period.
        """

        cutoff = ctx.message.created_at - period.delta

        cursor = self.conn.cursor()

        embeds = []

        for member in ctx.guild.members:
            if member.bot:
                continue

            lc = max(cutoff, member.joined_at or ctx.message.created_at)

            (num,) = cursor.execute(
                """
                SELECT COUNT(*)
                FROM contrib_activitymetadata_message_metadata
                WHERE guild_id = ? AND user_id = ? AND created_at > DATETIME(?)
                """,
                (ctx.guild.id, member.id, lc.isoformat()),
            ).fetchone()

            if num < number:
                embed = embed_from_member(member)
                embed.description = self.get_formatted_activity_for_member(member)
                embeds.append(embed)

        if not embeds:
            return await ctx.send("No members with that few messages.")
        elif len(embeds) == 1:
            await ctx.send("There is one member with that few messages.")
            await ctx.send(embed=embeds[0])
        else:
            await ctx.send(f"There are {len(embeds)} members with that few messages, I'm opening a menu with them.")
            menu = await ctx.list_menu(embeds, timeout=600, wait=True)
            await menu.message.delete()

    @commands.max_concurrency(1, commands.BucketType.guild)
    @mod()
    @commands.command("activityinrole")
    async def activity_for_role(self, ctx: SalamanderContext, role: str):
        """Get detailed activity for all members of a role"""

        roles = resolve_as_roles(ctx.guild, role)
        if not roles:
            raise UserFeedbackError(custom_message="That wasn't a role.")

        elif len(roles) > 1:
            raise UserFeedbackError(
                custom_message="There appears to be more than one role with that name, "
                "for safety, I won't act on this (use the role ID)"
            )

        actual_role = roles[0]

        def embedder(m: discord.Member) -> discord.Embed:
            embed = embed_from_member(m)
            embed.description = self.get_formatted_activity_for_member(m)
            return embed

        embeds = [embedder(m) for m in actual_role.members]
        if not embeds:
            return await ctx.send("No members with that few messages.")
        elif len(embeds) == 1:
            await ctx.send("There is one member with that few messages.")
            await ctx.send(embed=embeds[0])
        else:
            await ctx.send(f"There are {len(embeds)} members with that few messages, I'm opening a menu with them.")
            menu = await ctx.list_menu(embeds, timeout=600, wait=True)
            await menu.message.delete()

    @less_than.error
    @activity_for_role.error
    async def activity_for_role_error_hanlder(self, ctx, exc):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send(
                "You've given me what appears to be more than 1 role. If your role name has spaces in it, quote it."
            )
        elif isinstance(exc, commands.MaxConcurrencyReached):
            await ctx.send("A mod is using this currently already.")

    def get_formatted_activity_for_member(self, member: discord.Member) -> str:

        cursor = self.conn.cursor()
        row = cursor.execute(
            """
            SELECT DATETIME(
                CURRENT_TIMESTAMP,
                CAST(0 - max_days as TEXT) || ' days'
            )
            FROM contrib_activitymetadata_guild_settings
            WHERE guild_id = ? AND enabled
            """,
            (member.guild.id,),
        ).fetchone()

        if not row:
            return "Message metadata tracking has not been enabled for this server's members"

        expiration = datetime.fromisoformat(row[0])

        data = cursor.execute(
            """
            SELECT
                COUNT(*), MIN(created_at), MAX(created_at), channel_id
            FROM contrib_activitymetadata_message_metadata
            WHERE guild_id = ? AND user_id =? AND created_at > DATETIME(?)
            GROUP BY channel_id
            """,
            (member.guild.id, member.id, member.joined_at.isoformat()),
        ).fetchall()

        if member.joined_at > expiration:
            since = f"since joining this server on {member.joined_at:%B %d, %Y}"
        else:
            since = f"since the cutoff date for stored metadata ({expiration:%B %d, %Y})"

        if not data:
            return f"{member.mention} has not sent any messages that I've seen {since}."

        parts = []

        total = 0

        for number, earliest, latest, channel_id in data:

            if channel := member.guild.get_channel(channel_id):
                ear = datetime.fromisoformat(earliest).strftime("%B %d, %Y")

                total += number

                if number == 1:
                    parts.append(f"1 message in {channel.mention} on {ear}")
                else:
                    lat = datetime.fromisoformat(latest).strftime("%B %d, %Y")
                    if lat == ear:
                        parts.append(f"{number} messages in {channel.mention} on {ear}")
                    else:
                        parts.append(f"{number} messages in {channel.mention} between {ear} and {lat}")

        if total != 1:
            parts.insert(0, f"{member.mention} has sent {total} messages {since}.")
        else:
            parts.insert(0, f"{member.mention} has sent a single message {since}.")

        return "\n".join(parts)
