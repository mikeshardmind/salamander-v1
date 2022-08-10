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
import json
import logging
import random
from datetime import datetime, timezone
from fractions import Fraction
from typing import Iterable, Optional, Sequence, TypeVar

import apsw
import discord
from discord.ext import commands

from ...bot import Salamander, SalamanderContext, UserFeedbackError, get_contrib_data_path
from ...checks import admin_or_perms
from ...utils.converters import Weekday
from ...utils.embed_generators import embed_from_member

log = logging.getLogger("salamander.contrib_exts.qotw")


GUILD_SETTINGS_TABLE_CREATION_STATEMENT = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY NOT NULL,
    channel_id INTEGER DEFAULT NULL,
    last_qotw_at TEXT DEFAULT CURRENT_TIMESTAMP,
    qotw_day INTEGER DEFAULT 5,
    last_pinned_message_id INTEGER DEFAULT NULL
)
"""

CREATE_MEMBERS_TABLE_STATEMENT = """
CREATE TABLE IF NOT EXISTS member_questions (
    guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    current_question TEXT DEFAULT NULL,
    questions_since_select INTEGER DEFAULT 1,
    PRIMARY KEY (user_id, guild_id)
)
"""
# The default here isn't wrong, but it is intentionally offset for math.


T = TypeVar("T")


def resevoir_sample(iterable: Iterable[T]) -> T:
    it = iter(iterable)
    try:
        pick = next(it)
    except StopIteration:
        raise RuntimeError("Must provide a non-empty Iterable.")

    for n, x in enumerate(it, 2):
        if random.randrange(n) == 0:
            pick = x
    return pick


class QOTW(commands.Cog):
    """Question of the week"""

    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot
        self.conn = apsw.Connection(str(get_contrib_data_path("QOTW") / "qotw.db"))
        cursor = self.conn.cursor()

        for statement in (
            GUILD_SETTINGS_TABLE_CREATION_STATEMENT,
            CREATE_MEMBERS_TABLE_STATEMENT,
        ):
            cursor.execute(statement)
        cursor.close()

        self._loop: asyncio.Task | None = None

    @staticmethod
    async def remove_users(ids: Sequence[int]):

        conn = apsw.Connection(str(get_contrib_data_path("QOTW") / "qotw.db"))

        def _acr(conn: apsw.Connection, ids: Sequence[int]):
            with conn:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    DELETE FROM member_questions WHERE user_id = ?
                    """,
                    [(i,) for i in ids],
                )

        await asyncio.to_thread(_acr, conn, ids)

    @staticmethod
    async def remove_guilds(ids: Sequence[int]):
        conn = apsw.Connection(str(get_contrib_data_path("QOTW") / "qotw.db"))

        def _acr(conn: apsw.Connection, ids: Sequence[int]):
            with conn:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    DELETE FROM guild_settings WHERE guild_id = ?
                    """,
                    [(i,) for i in ids],
                )

        await asyncio.to_thread(_acr, conn, ids)

    def init(self):
        self._loop = asyncio.create_task(self.bg_loop())

    def cog_unload(self):
        if self._loop:
            self._loop.cancel()
        self.conn.close()

    async def bg_loop(self):

        cursor = self.conn.cursor()

        while True:
            await asyncio.sleep(600)
            now = datetime.now(timezone.utc)
            current_weekday = now.weekday()

            tsks = (
                self.handle_qotw(*row)
                for row in cursor.execute(
                    """
                    SELECT
                        guild_id, channel_id, last_pinned_message_id
                    FROM
                        guild_settings
                    WHERE
                        channel_id IS NOT NULL
                        AND qotw_day=?
                        AND DATE(last_qotw_at) < DATE(CURRENT_TIMESTAMP)
                    """,
                    (current_weekday,),
                )
            )

            results = await asyncio.gather(*tsks, return_exceptions=True)
            for t in results:
                if isinstance(t, Exception):
                    log.exception("Error in something: ", exc_info=t)

    async def handle_qotw(self, guild_id: int, channel_id: int, last_pinned_message_id: int):

        guild = self.bot.get_guild(guild_id)
        if guild is None or guild.unavailable:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return
        assert isinstance(channel, discord.TextChannel)

        if guild.large and not guild.chunked:
            await guild.chunk()

        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT user_id, current_question, questions_since_select
            FROM member_questions
            WHERE current_question IS NOT NULL AND guild_id=?
            """,
            (guild_id,),
        )

        questions = cursor.fetchall()

        if not questions:
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id, last_qotw_at)
                VALUES (?, CURRENT_TIMESTAMP)
                ON CONFLICT (guild_id)
                DO UPDATE SET
                    last_qotw_at=excluded.last_qotw_at
                """,
                (guild_id,),
            )
            return

        to_null: list[int] = []

        def gen_(question_list):
            for (mid, cq, qss) in question_list:
                if mem := guild.get_member(mid):  # ensure we only ask questions for people still here.
                    for _ in range(qss):
                        yield (mem, cq)
                else:
                    to_null.append(mid)  # And if they have left the server, we should reset them

        # could do something more clever here, but this isn't gonna be an issue
        selected_m, selected_question = resevoir_sample(gen_(questions))
        to_null.append(selected_m.id)

        with contextlib.suppress(discord.HTTPException):
            old_m = await channel.fetch_message(last_pinned_message_id)
            await old_m.unpin()

        new_m = await channel.send(f"**New Question of the Week** {selected_m.mention} asks:\n\n{selected_question}")

        last_pin = None
        with contextlib.suppress(discord.HTTPException):
            await new_m.pin()
            last_pin = new_m.id

        with self.conn:
            cursor.execute(
                """
                UPDATE member_questions
                SET
                    questions_since_select = questions_since_select + 1
                WHERE current_question IS NOT NULL AND guild_id=?
                """,
                (guild_id,),
            )

            cursor.execute(
                """
                WITH tn_ids AS (
                    SELECT value FROM json_each(json(?))
                )
                UPDATE member_questions
                SET
                    questions_since_select = 1,
                    current_question=NULL
                WHERE
                    guild_id = ?
                    AND EXISTS (
                        SELECT 1 FROM tn_ids WHERE value=member_questions.user_id
                    )
                """,
                (json.dumps(to_null), guild_id),
            )

            cursor.execute(
                """
                UPDATE guild_settings
                SET
                    last_qotw_at = CURRENT_TIMESTAMP,
                    last_pinned_message_id = :pin
                WHERE
                    guild_id = :guild_id
                """,
                dict(pin=last_pin, guild_id=guild_id),
            )

    @admin_or_perms(manage_messages=True)
    @commands.guild_only()
    @commands.group(name="qotwset")
    async def qotw_set(self, ctx: SalamanderContext):
        """Commands to manage QOTW"""

    @admin_or_perms(manage_messages=True)
    @commands.guild_only()
    @qotw_set.command(name="channel")
    async def qotw_set_channel(self, ctx: SalamanderContext, *, channel: discord.TextChannel):
        """Sets the channel for QOTW"""
        assert ctx.guild is not None

        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id, channel_id)
            VALUES (?, ?)
            ON CONFLICT (guild_id)
            DO UPDATE SET channel_id=excluded.channel_id
            """,
            (ctx.guild.id, channel.id),
        )

        await ctx.send("Channel set")

    @qotw_set.command(name="clearchannel")
    async def qotw_set_clearchan(self, ctx: SalamanderContext):
        """
        Clears the qotw channel if set.

        This will effectively disable QOTW in this server.
        """
        assert ctx.guild is not None

        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE guild_settings
            SET channel_id = NULL
            WHERE guild_id=?
            """,
            (ctx.guild.id,),
        )
        await ctx.send("Channel cleared.")

    @qotw_set.command(name="day")
    async def qotw_set_day(self, ctx: SalamanderContext, *, day: Weekday):
        """Sets the day of the week QOTW should be held on"""
        assert ctx.guild is not None

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id, qotw_day)
            VALUES (?,?)
            ON CONFLICT (guild_id)
            DO UPDATE SET qotw_day=excluded.qotw_day
            """,
            (ctx.guild.id, day.number),
        )
        await ctx.send(f"QOTW will be selected on {day}")

    @commands.guild_only()
    @qotw_set.command(name="force")
    async def force_qotw(self, ctx: SalamanderContext):
        """Force a new question to be asked"""
        assert ctx.guild is not None

        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT channel_id, last_pinned_message_id
            FROM guild_settings
            WHERE channel_id IS NOT NULL AND guild_id = ?
            """,
            (ctx.guild.id,),
        )
        row = cursor.fetchone()

        channel = None

        if row:
            channel_id, last_pinned_message_id = row
            channel = ctx.guild.get_channel(channel_id)

            if not channel:
                raise UserFeedbackError(custom_message="No QOTW channel has been set")

            await self.handle_qotw(ctx.guild.id, channel_id, last_pinned_message_id)

        else:
            raise UserFeedbackError(custom_message="No QOTW channel has been set")

    @admin_or_perms(manage_messages=True)
    @commands.guild_only()
    @qotw_set.command(name="view")
    async def view_pending(self, ctx: SalamanderContext):
        """View the currently pending questions"""
        assert ctx.guild is not None

        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT user_id, current_question, questions_since_select
            FROM member_questions
            WHERE current_question IS NOT NULL AND guild_id=?
            """,
            (ctx.guild.id,),
        )

        questions = cursor.fetchall()

        if not questions:
            return await ctx.send("No current questions.")

        total = 0

        filtered_questions = []

        for user_id, question, weight in questions:

            if m := ctx.guild.get_member(user_id):
                filtered_questions.append((m, question, weight))
                total += weight

        if not filtered_questions:
            return await ctx.send("No current questions")

        embeds = []

        n = len(filtered_questions)

        for idx, (member, question, weight) in enumerate(filtered_questions, 1):
            em = embed_from_member(member)
            em.add_field(name=f"Question {idx} of {n}", value=question, inline=False)
            em.add_field(name="Current odds of selection", value=f"{Fraction(weight, total)}")

            embeds.append(em)

        await ctx.list_menu(embeds)

    @commands.guild_only()
    @commands.command()
    async def qotwodds(self, ctx: SalamanderContext):
        """
        Get the current odds that your question is selected next.
        """
        assert ctx.guild is not None

        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT user_id, current_question, questions_since_select
            FROM member_questions
            WHERE current_question IS NOT NULL AND guild_id=?
            """,
            (ctx.guild.id,),
        )

        questions = cursor.fetchall()

        total = 0
        user_has_question = False
        user_question_weight = 0

        filtered_questions = []

        for user_id, question, weight in questions:

            if m := ctx.guild.get_member(user_id):
                filtered_questions.append((m, question, weight))
                total += weight
                if ctx.author.id == user_id:
                    user_has_question = True
                    user_question_weight = weight

        if not filtered_questions:
            return await ctx.send("There are no questions currently queued up, feel free to ask one.")
        elif user_has_question:
            return await ctx.send(
                f"There are currently {len(filtered_questions)} questions.\n"
                f"Your question currently has a {Fraction(user_question_weight, total)} chance of being selected."
            )
        else:
            return await ctx.send(
                f"There are currently {len(filtered_questions)} questions.\n"
                "You do not have a question submitted, but feel free to ask one."
            )

    @commands.guild_only()
    @commands.command()
    async def qotwask(self, ctx: SalamanderContext, *, question: str):
        """Ask a question."""

        assert ctx.guild is not None

        if len(question) > 1500:
            return await ctx.send("Please ask a shorter question (max 1500 characters).")

        cursor = self.conn.cursor()

        with self.conn:
            params = (ctx.guild.id, ctx.author.id, question)
            cursor.execute(
                """
                INSERT INTO member_questions (guild_id, user_id, current_question)
                VALUES (?,?,?)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET current_question=excluded.current_question
                """,
                params,
            )

        await ctx.send("Your submitted question for the next QOTW has been set.", delete_after=15)
        await asyncio.sleep(10)
        try:
            await ctx.message.delete()
        except Exception as exc:
            log.exception("Couldn't delete", exc_info=exc)

    @qotwask.before_invoke
    async def ask_before_invoke(self, ctx: SalamanderContext):
        assert ctx.guild is not None

        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT channel_id FROM guild_settings WHERE guild_id = ?
            """,
            (ctx.guild.id,),
        )
        row = cursor.fetchone()

        if not row:
            raise commands.CheckFailure()

        (channel_id,) = row
        if channel_id != ctx.channel.id:
            raise commands.CheckFailure()
