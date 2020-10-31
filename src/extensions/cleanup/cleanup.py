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
import logging
from datetime import timedelta

import discord
from discord.ext import commands

from ...bot import SalamanderContext
from ...checks import admin, mod_or_perms
from ...utils import Waterfall

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

        resp = await ctx.prompt(
            "Are you sure you want to remove all messages "
            "from any user who cannot see this channel? (yes, no)",
            options=("yes", "no"),
            timeout=30,
            delete_on_return=True,
        )

        if resp != "yes":
            return

        informational = await ctx.send(
            "This may take a while, I'll inform you when it is done."
        )

        async def safe_slow_delete(msgs):
            if msgs:
                if len(msgs) == 1:
                    await msgs[0].delete()
                else:
                    await ctx.channel.delete_messages(msgs)

        waterfall = Waterfall(12, 100, safe_slow_delete)
        try:

            waterfall.start()
            member_ids = {m.id for m in ctx.channel.members}

            async for msg in ctx.history(limit=None, before=informational.id):
                # artificial delay to avoid saturating ratelimits for something allowed to be a slow process
                # This one takes a hit once every 100 messages under the hood, making this ~ 8s/100m
                await asyncio.sleep(0.08)
                if msg.author.id not in member_ids:
                    waterfall.put(msg)

            waterfall.put(informational)

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
                f"{ctx.author.mention} The message removal process has finished."
            )

    @removegone.error
    async def concurrency_fail(self, ctx, exc):
        if isinstance(exc, commands.MaxConcurrencyReached):
            await ctx.send(
                "That command is already running for a channel in this server."
            )

    @commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
    @mod_or_perms(manage_messages=True)
    @commands.command()
    async def cleanup(self, ctx: SalamanderContext, number_or_strategy: int):
        """ Cleanup some messages """  # TODO: strategy support

        if number_or_strategy > 100:
            confirm = await ctx.prompt(
                f"Are you sure you want to delete up to {number_or_strategy} messages?",
                options=("yes", "no"),
                timeout=30,
                delete_on_return=True,
            )
            if confirm == "no":
                return

        # I think waterfall use might make sense here? IDK --Liz
        # Maybe, but I get the feeling it won't feel responsive enough. -- Sinbad

        to_delete = [ctx.message]

        cutoff = ctx.message.created_at - timedelta(days=10)

        # Strategy might go in params here
        # Don't use after param, changes API behavior. Can add oldest_first=False,
        # but this will increase the needed underlying api calls.
        async for message in ctx.history(limit=number_or_strategy, before=ctx.message):
            # Strategy support goes here

            if message.created_at < cutoff:
                break

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
