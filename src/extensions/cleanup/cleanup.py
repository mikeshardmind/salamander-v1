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
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord.ext import commands

from ...bot import SalamanderContext, UserFeedbackError
from ...checks import admin, mod_or_perms
from ...utils import Waterfall
from ...utils.parsing import parse_positive_number, parse_snowflake

log = logging.getLogger("salamander.extensions.cleanup")


class Cleanup(commands.Cog):
    """ Quick message cleanup """

    @commands.max_concurrency(1, commands.BucketType.guild)
    @commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
    @admin()
    @commands.command()
    async def removegone(self, ctx: SalamanderContext):
        """
        Removes messages from those who can no longer see the channel

        Can be used if handling deletion requests for privacy reasons
        Is intentionally very slow, limited to admins only, and can only run one at a time
        """

        if not await ctx.yes_or_no(
            "Are you sure you want to remove all messages from any user who cannot see this channel? (yes, no)",
            delete_on_return=True,
        ):
            return

        informational = await ctx.send("This may take a while, I'll inform you when it is done.")

        lock = asyncio.Lock()

        async def safe_slow_delete(msgs):
            async with lock:
                if msgs:
                    if len(msgs) == 1:
                        try:
                            await msgs[0].delete()
                        except discord.NotFound:
                            pass

                    # some wiggle room included
                    cutoff = datetime.utcnow() - timedelta(days=13, hours=22)

                    mass_deletable = []
                    for m in msgs:
                        if m.created_at > cutoff:
                            mass_deletable.append(m)
                        else:
                            try:
                                await m.delete()
                            except discord.NotFound:
                                pass
                            await asyncio.sleep(2)

                    if mass_deletable:
                        await ctx.channel.delete_messages(mass_deletable)
                        await asyncio.sleep(1)

        waterfall = Waterfall(12, 100, safe_slow_delete)
        try:

            waterfall.start()
            member_ids = {m.id for m in ctx.channel.members}

            async for msg in ctx.history(limit=None, before=informational):
                # artificial delay to avoid saturating ratelimits for something allowed to be a slow process
                # This one takes a hit once every 100 messages under the hood, making this ~ 8s/100m
                await asyncio.sleep(0.08)
                if msg.author.id not in member_ids:
                    waterfall.put(msg)

        except Exception as exc:
            log.exception("Error during removegone", exc_info=exc)
            await waterfall.stop(wait=True)
            await ctx.send(
                f"{ctx.author.mention} something went wrong during the "
                "message removal process. The error has been logged.",
                allowed_mentions=discord.AllowedMentions(users=[ctx.author]),
            )
        else:
            await waterfall.stop(wait=True)
            await ctx.send(
                f"{ctx.author.mention} The message removal process has finished.",
                allowed_mentions=discord.AllowedMentions(users=[ctx.author]),
            )

    @removegone.error
    async def concurrency_fail(self, ctx, exc):
        if isinstance(exc, commands.MaxConcurrencyReached):
            await ctx.send("That command is already running for a channel in this server.")

    @commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
    @mod_or_perms(manage_messages=True)
    @commands.group()
    async def cleanup(self, ctx: SalamanderContext):
        """ Message cleanup tools """

        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @cleanup.command(name="number")
    async def cleanup_number(self, ctx: SalamanderContext, number):
        """ Cleanup some number of messages within the last 10 days. """

        limit = parse_positive_number(number, 1e7)
        if not limit:
            raise UserFeedbackError(custom_message="You must provide a positive number of 1 million or less.")

        if limit > 100:
            if not await ctx.yes_or_no(
                f"Are you sure you want to delete up to {limit} messages?",
                delete_on_return=True,
            ):
                return

        await self._cleanup(ctx, limit=limit)

    @cleanup.command(name="before")
    async def cleanup_before(self, ctx: SalamanderContext, before):
        """ Cleanup messages before a specific message ID within the last 10 days. """

        snowflake = parse_snowflake(before)
        if not snowflake:
            raise UserFeedbackError(custom_message="That did not look like a valid message ID.")

        before_obj = discord.Object(id=snowflake)
        if before_obj.created_at < ctx.message.created_at - timedelta(days=10):
            raise UserFeedbackError(custom_message="This message is older than the 10 day cutoff.")

        if not await ctx.yes_or_no(
            "Are you sure you want to delete all the messages before this ID within the last 10 days?",
            delete_on_return=True,
        ):
            return

        await self._cleanup(ctx, before=before_obj)

    @cleanup.command(name="after")
    async def cleanup_after(self, ctx: SalamanderContext, after):
        """ Cleanup all messages after a specific message ID within the last 10 days. """

        snowflake = parse_snowflake(after)
        if not snowflake:
            raise UserFeedbackError(custom_message="That did not look like a valid message ID.")

        after_obj = discord.Object(id=snowflake)
        if after_obj.created_at < ctx.message.created_at - timedelta(days=10):
            raise UserFeedbackError(custom_message="This message is older than the 10 day cutoff.")

        if not await ctx.yes_or_no(
            "Are you sure you want to delete all the messages after the provided message ID?",
            delete_on_return=True,
        ):
            return

        await self._cleanup(ctx, after=after_obj)

    @cleanup.command(name="between")
    async def cleanup_between(self, ctx: SalamanderContext, first, second):
        """
        Cleanup messages between two provided message IDs within the last 10 days.
        """

        snowflake = parse_snowflake(first)
        if not snowflake:
            raise UserFeedbackError(custom_message="The first provided ID did not look like a valid message ID.")

        first_obj = discord.Object(id=snowflake)
        if first_obj.created_at < ctx.message.created_at - timedelta(days=10):
            raise UserFeedbackError(custom_message="The first provided message ID is older than the 10 day cutoff.")

        snowflake = parse_snowflake(first)
        if not snowflake:
            raise UserFeedbackError(custom_message="The second provided ID did not look like a valid message ID.")

        second_obj = discord.Object(id=snowflake)
        if second_obj.created_at < ctx.message.created_at - timedelta(days=10):
            raise UserFeedbackError(custom_message="The second provided message ID is older than the 10 day cutoff.")

        if second.obj.created_at < first_obj.created_at:
            raise UserFeedbackError(
                custom_message="The first message ID provided should be the earlier one. (Not continuing in case of accidental misuse.)"
            )

        if not await ctx.yes_or_no(
            "Are you sure you want to delete all the messages between the provided message IDs?",
            delete_on_return=True,
        ):
            return

        await self._cleanup(ctx, before=second_obj, after=first_obj)

    async def _cleanup(
        self,
        ctx: SalamanderContext,
        *,
        limit: Optional[int] = None,
        before: Optional[discord.Snowflake] = None,
        after: Optional[discord.Snowflake] = None,
    ):

        # I think waterfall use might make sense here? IDK --Liz
        # Maybe, but I get the feeling it won't feel responsive enough. -- Sinbad

        to_delete = [ctx.message]

        before = before or ctx.message
        cutoff = after.created_at if after else ctx.message.created_at - timedelta(days=10)

        # Don't use after param, changes API behavior. Can add oldest_first=False,
        # but this will increase the needed underlying api calls.
        async for message in ctx.history(limit=limit, before=before):

            if message.created_at < cutoff:
                break

            if not message.pinned:
                to_delete.append(message)

            if len(to_delete) == 100:
                await ctx.channel.delete_messages(to_delete)
                to_delete = []

        if to_delete:
            if len(to_delete) == 1:
                # Why does discord's API care about this?
                await to_delete[0].delete()
            else:
                await ctx.channel.delete_messages(to_delete)
