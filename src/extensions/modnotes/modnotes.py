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

from datetime import datetime
from typing import Iterator, NamedTuple

import discord
from discord.ext import commands

from ...bot import Salamander, SalamanderContext, UserFeedbackError
from ...checks import mod
from ...utils.converters import StrictMemberConverter


class Note(NamedTuple):
    guild_id: int
    mod_id: int
    target_id: int
    note: str
    created_at: str

    def embed(self, ctx: SalamanderContext) -> discord.Embed:
        e = discord.Embed(
            description=self.note,
            timestamp=datetime.fromisoformat(self.created_at),
            color=ctx.me.color,
        )
        author = ctx.guild.get_member(self.mod_id)
        subject = ctx.guild.get_member(self.target_id)
        a_str = (
            f"{author} ({self.mod_id})" if author else f"Unknown Author ({self.mod_id})"
        )
        s_str = (
            f"{subject} ({self.target_id})"
            if subject
            else f"Unknown Subject ({self.target_id})"
        )
        e.add_field(name="Note Author", value=a_str)
        e.add_field(name="Note Subject", value=s_str)
        return e


class ModNotes(commands.Cog):
    """
    Store moderator notes.
    """

    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot

    def insert(self, *, mod_id: int, target_id: int, guild_id: int, note: str):
        cursor = self.bot._conn.cursor()

        with self.bot._conn:
            cursor.executemany(
                """
                INSERT INTO user_settings (user_id) VALUES (?)
                ON CONFLICT (user_id) DO NOTHING
                """,
                ((mod_id,), (target_id,)),
            )

            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (guild_id,),
            )

            cursor.executemany(
                """
                INSERT INTO member_settings (guild_id, user_id) VALUES (?,?)
                ON CONFLICT (guil_id, user_id) DO NOTHING
                """,
                ((guild_id, target_id), (guild_id, mod_id)),
            )

            cursor.execute(
                """
                INSERT INTO mod_notes_on_members (guild_id, mod_id, target_id, note)
                VALUES (?,?,?,?)
                """,
                (guild_id, mod_id, target_id, note),
            )

    def find_by_author(self, mod_id: int) -> Iterator[Note]:
        cursor = self.bot._conn.cursor()

        for items in cursor.execute(
            """
            SELECT guild_id, mod_id, target_id, note, created_at
            FROM mod_notes_on_members
            WHERE mod_id=?
            ORDER BY created_at
            """,
            (mod_id,),
        ):
            yield Note(*items)

    def find_by_author_in_guild(self, *, mod_id: int, guild_id: int) -> Iterator[Note]:
        cursor = self.bot._conn.cursor()
        for items in cursor.execute(
            """
            SELECT guild_id, mod_id, target_id, note, created_at
            FROM mod_notes_on_members
            WHERE mod_id=? AND guild_id=?
            ORDER BY created
            """,
            (mod_id, guild_id),
        ):
            yield Note(*items)

    def find_by_member(self, *, member_id: int, guild_id: int) -> Iterator[Note]:
        cursor = self.bot._conn.cursor()
        for items in cursor.execute(
            """
            SELECT guild_id, mod_id, target_id, note, created_at
            FROM mod_notes_on_members
            WHERE target_id=? AND guild_id=?
            ORDER BY created
            """,
            (member_id, guild_id),
        ):
            yield Note(*items)

    def find_by_guild(self, guild_id: int) -> Iterator[Note]:
        cursor = self.bot._conn.cursor()
        for items in cursor.execute(
            """
            SELECT guild_id, mod_id, target_id, note, created_at
            FROM mod_notes_on_members
            WHERE guild_id=?
            ORDER BY created
            """,
            (guild_id,),
        ):
            yield Note(*items)

    @mod()
    @commands.command()
    async def makemodnote(
        self, ctx: SalamanderContext, who: StrictMemberConverter, *, note: str
    ):
        """ Make a note about a user """

        if not who.id:
            raise UserFeedbackError(custom_message="That didn't look like a user or ID")

        self.insert(
            mod_id=ctx.author.id, target_id=who.id, note=note, guild_id=ctx.guild.id,
        )
        await ctx.send("Note created.")

    @mod()
    @commands.group()
    async def getmodnotes(self, ctx: SalamanderContext):
        """ Get notes """
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @mod()
    @getmodnotes.command()
    async def about(self, ctx: SalamanderContext, who: StrictMemberConverter):
        """ Get notes about a user """

        if not who.id:
            raise UserFeedbackError(custom_message="That didn't look like a user or ID")

        notes = [
            n.embed(ctx)
            for n in self.find_by_member(member_id=who.id, guild_id=ctx.guild.id)
        ]
        if not notes:
            return await ctx.send("No mod notes about this user")
        mx = len(notes)
        for i, n in enumerate(notes, 1):
            n.title = f"Showing #{i} of {mx} found notes"

        await ctx.list_menu(notes)

    @about.error
    async def too_many_consistency(self, ctx, exc):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send("That didn't look like a single user to me.")
