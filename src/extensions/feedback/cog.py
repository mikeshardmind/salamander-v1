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

import re
import uuid

import discord
from discord.ext import commands

from ...bot import IncompleteInputError, Salamander, SalamanderContext, UserFeedbackError
from ...utils import format_list


class Feedback(commands.Cog):
    """ Commands for sending feedback about the bot """

    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot

    @commands.is_owner()
    @commands.group()
    async def feedbackset(self, ctx: SalamanderContext):
        """ Settings commands for configuring accepted feedback """

        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @commands.is_owner()
    @feedbackset.command(ignore_extra=False)
    async def createtype(self, ctx: SalamanderContext, name: str):
        """ Create a type of feedback (see "fullcreate" command as well) """
        name = name.casefold()
        if re.match(r"\s", name):
            raise UserFeedbackError(
                custom_message="Feedback types should not contain any spaces. "
                "This makes them easier to work with for users."
            )
        cursor = self.bot._conn.cursor()

        (already_exists,) = cursor.execute(
            """
            SELECT EXISTS(SELECT 1 FROM feedback_types WHERE feedback_type = ?)
            """,
            (name,),
        ).fetchone()

        if already_exists:
            raise UserFeedbackError(custom_message="That's already a feedback type")

        cursor.execute(
            """
            INSERT INTO feedback_types(feedback_type) VALUES(?)
            ON CONFLICT (feedback_type) DO NOTHING
            """
        )

        await ctx.send("Feedback type created.")

    @createtype.error
    async def create_type_error(self, ctx: SalamanderContext, exc: Exception):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send(
                "Feedback types should not contain any spaces. This makes them easier to work with for users."
            )

    @commands.is_owner()
    @feedbackset.command()
    async def setchannelfortype(self, ctx: SalamanderContext, channel: discord.TextChannel, typename: str):
        """
        Sets a channel to recieve feedback for a specific type
        """

        name = typename.casefold()
        cursor = self.bot._conn.cursor()

        (already_exists,) = cursor.execute(
            """
            SELECT EXISTS(SELECT 1 FROM feedback_types WHERE feedback_type = ?)
            """,
            (name,),
        ).fetchone()

        if not already_exists:
            raise UserFeedbackError(custom_message="That type doesn't exist.")

        cursor.execute(
            """
            UPDATE feedback_types
            SET destination_id = ?
            WHERE feedback_type = ?
            """,
            (channel.id, name),
        )

        await ctx.send("Feedback channel set.")

    @commands.is_owner()
    @feedbackset.command()
    async def setautoresponsefortype(self, ctx: SalamanderContext, typename: str, *, response: str):
        """Set an autoresponse to a feedback type

        By default, there is no response.
        """

        name = typename.casefold()
        cursor = self.bot._conn.cursor()

        (already_exists,) = cursor.execute(
            """
            SELECT EXISTS(SELECT 1 FROM feedback_types WHERE feedback_type = ?)
            """,
            (name,),
        ).fetchone()

        if not already_exists:
            raise UserFeedbackError(custom_message="That type doesn't exist.")

        cursor.execute(
            """
            UPDATE feedback_types
            SET autoresponse = ?
            WHERE feedback_type = ?
            """,
            (response, name),
        )

        await ctx.send("Feedback autoresponse set.")

    @commands.is_owner()
    @feedbackset.command()
    async def fullcreate(
        self,
        ctx: SalamanderContext,
        typename: str,
        channel: discord.TextChannel,
        *,
        response: str = None,
    ):
        """Create a feedback type, setting the response channel and
        optionally an autoresponse in a single command.

        Note: This will also overwrite settings for an existing type,
        it is assumed if you are using this command you already know how this works.
        """
        cursor = self.bot._conn.cursor()
        name = typename.casefold()
        if re.match(r"\s", name):
            raise UserFeedbackError(
                custom_message="Feedback types should not contain any spaces. "
                "This makes them easier to work with for users."
            )

        cursor.execute(
            """
            INSERT INTO feedback_types (feedback_type, destination_id, autoresponse)
            VALUES (?,?,?)
            ON CONFLICT (feedback_type)
            DO UPDATE SET
                destination_id=excluded.destination_id,
                autoresponse=excluded.autoresponse
            """,
            (name, channel.id, response),
        )

        if not response:
            await ctx.send(f"Feedback type created or update to use {channel.mention} without an autoresponse.")
        else:
            await ctx.send(f"Feedback type created or updated to use {channel.mention} with an autoresponse.")

    @commands.is_owner()
    @feedbackset.command()
    async def deletetype(self, ctx: SalamanderContext, typename: str):
        """ Delete a feedback type """
        name = typename.casefold()
        cursor = self.bot._conn.cursor()

        (already_exists,) = cursor.execute(
            """
            SELECT EXISTS(SELECT 1 FROM feedback_types WHERE feedback_type = ?)
            """,
            (name,),
        ).fetchone()

        if not already_exists:
            raise UserFeedbackError(custom_message="That type doesn't exist.")

        if not await ctx.yes_or_no(
            "Are you sure you want to delete this feedback type? "
            "Doing so will also remove all feedback you have gotten for this type. (yes/no)",
        ):
            return

        cursor.execute(
            """
            DELETE FROM feedback_types WHERE feedback_type = ?
            """,
            (name,),
        )

        await ctx.send("Feedback type deleted.")

    @commands.group()
    async def feedback(self, ctx: SalamanderContext):
        """ Commands for sending feedback """

        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @commands.cooldown(5, 40, commands.BucketType.user)
    @feedback.command()
    async def send(self, ctx: SalamanderContext, feedback_type: str, *, feedback: str):
        """ Send feedback """

        name = feedback_type.casefold()
        cursor = self.bot._conn.cursor()
        row = cursor.execute(
            """
            SELECT autoresponse, destination_id FROM feedback_types WHERE feedback_type = ?
            """,
            (name,),
        ).fetchone()

        if not row:
            raise IncompleteInputError(
                custom_message="That feedback type doesn't seem to exist. (Hint: try using the `feedback types` command)",
                reset_cooldown=True,
            )

        response, channel_id = row

        with self.bot._conn:

            uuid4 = str(uuid.uuid4())

            cursor.execute(
                """
                INSERT INTO user_settings(user_id) VALUES (?)
                ON CONFLICT (user_id)
                DO NOTHING
                """,
                (ctx.author.id,),
            )

            cursor.execute(
                """
                INSERT INTO feedback_entries(feedback_type, user_id, uuid, feedback) VALUES (?,?,?,?)
                """,
                (name, ctx.author.id, uuid4, feedback),
            )

        if response:
            await ctx.send(response)

        if channel_id:
            if destination := self.bot.get_channel(channel_id):
                embed = discord.Embed(description=feedback, color=destination.guild.me.color)
                embed.set_author(
                    name=f"Feedback from {ctx.author}",
                    url=ctx.author.avatar_url_as(static_format="png"),
                )
                embed.add_field(name="Feedback type", value=name)
                embed.add_field(name="Feedback uuid", value=uuid4)
                embed.set_footer(text=f"User ID: {ctx.author.id}")
                await destination.send(embed=embed)

    @commands.cooldown(1, 10, commands.BucketType.channel)
    @feedback.command()
    async def types(self, ctx: SalamanderContext):
        """ View the types of feedback """

        cursor = self.bot._conn.cursor()
        type_names = tuple(
            name
            for (name,) in cursor.execute(
                """
                SELECT feedback_type FROM feedback_types
                ORDER BY feedback_type ASC
                """
            )
        )

        if not type_names:
            await ctx.send("No feedback types have been configured.")
        else:
            await ctx.send_paged(
                format_list(type_names),
                prepend="This bot accepts feedback of the following types:\n",
            )
