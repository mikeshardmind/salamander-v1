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
from datetime import datetime, timedelta, timezone

import discord
from discord.app_commands import Group
from discord.ext import commands

from ...bot import SalamanderContext, YesNoView
from ...checks import admin, mod_or_perms
from ...utils import Waterfall
from ...utils.parsing import parse_positive_number, parse_snowflake

log = logging.getLogger("salamander.extensions.cleanup")


class Cleanup(commands.Cog):
    """Quick message cleanup"""

    # not a command currently..
    async def removegone(self, ctx: SalamanderContext):
        """
        Removes messages from those who can no longer see the channel

        Can be used if handling deletion requests for privacy reasons
        Is intentionally very slow, limited to admins only, and can only run one at a time
        """
        assert not isinstance(ctx.channel, (discord.DMChannel, discord.PartialMessageable, discord.GroupChannel))

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
                    cutoff = datetime.now(timezone.utc) - timedelta(days=13, hours=22)

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
                        assert not isinstance(
                            ctx.channel, (discord.DMChannel, discord.PartialMessageable, discord.GroupChannel)
                        )
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
    async def concurrency_fail(self, ctx: SalamanderContext, exc: commands.CommandError):
        if isinstance(exc, commands.MaxConcurrencyReached):
            await ctx.send("That command is already running for a channel in this server.")

    grp = Group(name="cleanup", guild_only=True, default_permissions=discord.Permissions(manage_messages=True))

    @grp.command(name="number")
    async def cleanup_number(self, interaction: discord.Interaction, number: discord.app_commands.Range[int, 1, 1e7]):
        """Cleanup some number of messages within the last 10 days."""

        view = YesNoView(interaction.user.id)

        await interaction.response.send_message(ephemeral=True, content="Delete up to %d messages?" % number, view=view)
        await asyncio.wait({view.wait()}, timeout=30)
        view.stop()

        await interaction.edit_original_response(view=None)

        if view.value is True:
            channel = interaction.channel
            assert channel
            assert isinstance(channel, (discord.TextChannel , discord.Thread , discord.VoiceChannel)), "guild only"
            await self._cleanup(channel, limit=number)

    async def _cleanup(
        self,
        channel: discord.TextChannel | discord.Thread | discord.VoiceChannel,
        *,
        limit: int | None = None,
        before: discord.Message | discord.Object | None = None,
        after: discord.Message | discord.Object | None = None,
    ):

        # I think waterfall use might make sense here? IDK --Liz
        # Maybe, but I get the feeling it won't feel responsive enough. -- Sinbad

        to_delete = []

        before = before or None
        cutoff = after.created_at if after else discord.utils.utcnow() - timedelta(days=10)

        # Don't use after param, changes API behavior. Can add oldest_first=False,
        # but this will increase the needed underlying api calls.
        async for message in channel.history(limit=limit, before=before):

            if message.created_at < cutoff:
                break

            if not message.pinned:
                to_delete.append(message)

            if len(to_delete) == 100:
                await channel.delete_messages(to_delete)
                to_delete = []

        if to_delete:
            if len(to_delete) == 1:
                # Why does discord's API care about this?
                await to_delete[0].delete()
            else:
                await channel.delete_messages(to_delete)
