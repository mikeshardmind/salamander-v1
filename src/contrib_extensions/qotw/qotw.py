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
import random
from datetime import datetime, timezone
from fractions import Fraction
from typing import Optional

import apsw
import discord
from discord.ext import commands

from ...bot import Salamander, SalamanderContext, UserFeedbackError
from ...checks import admin_or_perms
from ...utils.converters import Weekday
from ...utils.embed_generators import embed_from_member

log = logging.getLogger("salamander.contrib_exts.qotw")


GUILD_SETTINGS_TABLE_CREATION_STATEMENT = """
CREATE TABLE IF NOT EXISTS contrib_qotw_guild_settings (
    guild_id INTEGER PRIMARY KEY NOT NULL,
    channel_id INTEGER DEFAULT NULL,
    last_qotw_at TEXT DEFAULT CURRENT_TIMESTAMP,
    qotw_day INTEGER DEFAULT 5,
    last_pinned_message_id INTEGER DEFAULT NULL
)
"""

CREATE_MEMBERS_TABLE_STATEMENT = """
CREATE TABLE IF NOT EXISTS contrib_qotw_members (
    guild_id INTEGER NOT NULL REFERENCES contrib_qotw_guild_settings(guild_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    current_question TEXT DEFAULT NULL,
    questions_since_select INTEGER DEFAULT 1,
    PRIMARY KEY (user_id, guild_id)
)
"""

CREATE_HISTORICAL_ALL = """
CREATE TABLE IF NOT EXISTS contrib_qotw_all_history (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    when_asked TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guild_id, user_id) REFERENCES contrib_qotw_members (guild_id, user_id)
        ON UPDATE CASCADE ON DELETE CASCADE
)
"""

SELECTED_QUESTION_HISTORY = """
CREATE TABLE IF NOT EXISTS contrib_qotw_selected_history (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    question TEXT,
    when_selected TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guild_id, user_id) REFERENCES contrib_qotw_members (guild_id, user_id)
        ON UPDATE CASCADE ON DELETE CASCADE
)
"""

# The default here isn't wrong, but it is intentionally offset for math.


def resevoir_sample(iterable):
    for n, x in enumerate(iterable, 1):
        if random.randrange(n) == 0:  # nosec
            pick = x
    return pick


class QOTW(commands.Cog):
    """ Question of the week """

    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot
        self.conn = self.bot._conn
        cursor = self.conn.cursor()

        for statement in (
            GUILD_SETTINGS_TABLE_CREATION_STATEMENT,
            CREATE_MEMBERS_TABLE_STATEMENT,
            CREATE_HISTORICAL_ALL,
            SELECTED_QUESTION_HISTORY,
        ):
            cursor.execute(statement)
        cursor.close()

        self._loop: Optional[asyncio.Task] = None

    @staticmethod
    def remove_tables_from_connection(conn: apsw.Connection):
        cursor = conn.cursor()
        with conn:
            cursor.execute("""DROP TABLE contrib_qotw_all_history""")
            cursor.execute("""DROP TABLE contrib_qotw_selected_history""")
            cursor.execute("""DROP TABLE contrib_qotw_members""")
            cursor.execute("""DROP TABLE contrib_qotw_guild_settings""")

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
            now = datetime.utcnow().replace(tzinfo=timezone.utc)
            current_weekday = now.weekday()

            tsks = (
                self.handle_qotw(*row)
                for row in cursor.execute(
                    """
                    SELECT guild_id, channel_id, last_pinned_message_id
                    FROM contrib_qotw_guild_settings
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

    async def handle_qotw(
        self, guild_id: int, channel_id: int, last_pinned_message_id: int
    ):

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return

        cursor = self.conn.cursor()

        questions = cursor.execute(
            """
            SELECT user_id, current_question, questions_since_select
            FROM contrib_qotw_members
            WHERE current_question IS NOT NULL AND guild_id=?
            """,
            (guild_id,),
        ).fetchall()

        if not questions:
            cursor.execute(
                """
                INSERT INTO contrib_qotw_guild_settings (guild_id, last_qotw_at)
                VALUES (?, CURRENT_TIMESTAMP)
                ON CONFLICT (guild_id)
                DO UPDATE SET
                    last_qotw_at=excluded.last_qotw_at
                """,
                (guild_id,),
            )
            return

        def gen_(question_list):
            for (mid, cq, qss) in question_list:
                if mem := guild.get_member(
                    mid
                ):  # ensure we only ask questions for people still here.
                    for i in range(qss):
                        yield (mem, cq)

        # could do something more clever here, but this isn't gonna be an issue
        selected_m, selected_question = resevoir_sample(gen_(questions))

        with contextlib.suppress(discord.HTTPException):
            old_m = await channel.fetch_message(last_pinned_message_id)
            await old_m.unpin()

        new_m = await channel.send(
            f"**New Question of the Week** {selected_m.mention} asks:\n\n{selected_question}"
        )

        last_pin = None
        with contextlib.suppress(discord.HTTPException):
            await new_m.pin()
            last_pin = new_m.id

        with self.conn:
            cursor.execute(
                """
                UPDATE contrib_qotw_members
                SET
                    questions_since_select = questions_since_select + 1
                WHERE current_question IS NOT NULL AND guild_id=?
                """,
                (guild_id,),
            )

            cursor.execute(
                """
                UPDATE contrib_qotw_members
                SET questions_since_select = 1, current_question=NULL
                WHERE guild_id = ? AND  user_id = ?
                """,
                (guild_id, selected_m.id),
            )

            cursor.execute(
                """
                INSERT INTO contrib_qotw_selected_history (guild_id, user_id, question)
                VALUES (?,?,?)
                """,
                (guild_id, selected_m.id, selected_question),
            )

            cursor.execute(
                """
                UPDATE contrib_qotw_guild_settings
                SET last_qotw_at = CURRENT_TIMESTAMP, last_pinned_message_id = :pin
                WHERE guild_id = :guild_id
                """,
                dict(pin=last_pin, guild_id=guild_id),
            )

    @admin_or_perms(manage_messages=True)
    @commands.guild_only()
    @commands.group(name="qotwset")
    async def qotw_set(self, ctx: SalamanderContext):
        """ Commands to manage QOTW """
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @admin_or_perms(manage_messages=True)
    @commands.guild_only()
    @qotw_set.command(name="channel")
    async def qotw_set_channel(
        self, ctx: SalamanderContext, *, channel: discord.TextChannel
    ):
        """ Sets the channel for QOTW """

        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT INTO contrib_qotw_guild_settings (guild_id, channel_id)
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

        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE contrib_qotw_guild_settings
            SET channel_id = NULL
            WHERE guild_id=?
            """,
            (ctx.guild.id,),
        )
        await ctx.send("Channel cleared.")

    @qotw_set.command(name="day")
    async def qotw_set_day(self, ctx: SalamanderContext, *, day: Weekday):
        """ Sets the day of the week QOTW should be held on """

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO contrib_qotw_guild_settings (guild_id, qotw_day)
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
        """ Force a new question to be asked """

        cursor = self.conn.cursor()

        row = cursor.execute(
            """
            SELECT channel_id, last_pinned_message_id
            FROM contrib_qotw_guild_settings
            WHERE
                channel_id IS NOT NULL
                AND guild_id = ?
            """,
            (ctx.guild.id,),
        ).fetchone()

        channel = None

        if row:
            channel_id, last_pinned_message_id = row
            channel = ctx.guild.get_channel(channel_id)

        if not channel:
            raise UserFeedbackError(custom_message="No QOTW channel has been set")

        await self.handle_qotw(ctx.guild.id, channel_id, last_pinned_message_id)

    @admin_or_perms(manage_messages=True)
    @commands.guild_only()
    @qotw_set.command(name="view")
    async def view_pending(self, ctx: SalamanderContext):
        """ View the currently pending questions """

        cursor = self.conn.cursor()

        questions = cursor.execute(
            """
            SELECT user_id, current_question, questions_since_select
            FROM contrib_qotw_members
            WHERE current_question IS NOT NULL AND guild_id=?
            """,
            (ctx.guild.id,),
        ).fetchall()

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
            em.add_field(
                name="Current odds of selection", value=f"{Fraction(weight, total)}"
            )

            embeds.append(em)

        await ctx.list_menu(embeds)

    @commands.guild_only()
    @commands.command()
    async def qotwodds(self, ctx: SalamanderContext):
        """
        Get the current odds that your question is selected next.
        """

        cursor = self.conn.cursor()

        questions = cursor.execute(
            """
            SELECT user_id, current_question, questions_since_select
            FROM contrib_qotw_members
            WHERE current_question IS NOT NULL AND guild_id=?
            """,
            (ctx.guild.id,),
        ).fetchall()

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
    async def ask(self, ctx: SalamanderContext, *, question: str):
        if len(question) > 1500:
            return await ctx.send(
                "Please ask a shorter question (max 1500 characters)."
            )

        cursor = self.conn.cursor()

        with self.conn:
            params = (ctx.guild.id, ctx.author.id, question)
            cursor.execute(
                """
                INSERT INTO contrib_qotw_members (guild_id, user_id, current_question)
                VALUES (?,?,?)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET current_question=excluded.current_question
                """,
                params,
            )
            cursor.execute(
                """
                INSERT INTO contrib_qotw_all_history (guild_id, user_id, question)
                VALUES(?,?,?)
                """,
                params,
            )

        await ctx.send(
            "Your submitted question for the next QOTW has been set.", delete_after=15
        )
        await asyncio.sleep(10)
        try:
            await ctx.message.delete()
        except Exception as exc:
            log.exception("Couldn't delete", exc_info=exc)

    @ask.before_invoke
    async def ask_before_invoke(self, ctx: SalamanderContext):
        cursor = self.conn.cursor()

        row = cursor.execute(
            """
            SELECT channel_id FROM contrib_qotw_guild_settings WHERE guild_id = ?
            """,
            (ctx.guild.id,),
        ).fetchone()

        if not row:
            raise commands.CheckFailure()

        (channel_id,) = row
        if channel_id != ctx.channel.id:
            raise commands.CheckFailure()
