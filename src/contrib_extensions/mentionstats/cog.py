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
import string
from collections import defaultdict
from datetime import datetime as dt
from datetime import timedelta as td
from datetime import timezone as tz
from typing import MutableMapping, Optional, Sequence

import attr
import discord
from discord.ext import commands, tasks
from discord.http import handle_message_parameters
from lru import LRU

from ...bot import Salamander, SalamanderContext, UserFeedbackError, get_contrib_data_path
from ...checks import admin_or_perms
from ...utils.provisional import rapid_storage


@attr.s(auto_attribs=True, frozen=True, kw_only=True)
class GuildSettings:
    track_mass_mentions: bool = True
    last_mass_mention_ts: int | None = None
    last_mass_mention_notice: tuple[int, int] | None = None
    mass_mention_notice_template: str = "This server has lasted $days without a mass mention."

    @property
    def days_since_last_mass_mention(self) -> int | None:
        if self.last_mass_mention_ts:
            return (dt.now(tz.utc) - dt.utcfromtimestamp(self.last_mass_mention_ts).replace(tzinfo=tz.utc)).days


class MentionStorage(rapid_storage.Storage):
    """
    While this could be done easily via manual sql,
    We are intentionally using a provisional util here to provide an example of how to use it.

    rapid_storage is relatively optimized for this pattern of access,
    and does not require a strong knowledge of SQL
    """

    @classmethod
    def get_store(cls, version: int):
        dbpath = get_contrib_data_path("mentionstats") / "mentionstats.db"
        backend = rapid_storage.SQLiteBackend.create_backend_instance_sync(dbpath, "mentionstore", version)
        return cls(backend)

    def track_mass_mentions(self, guild: discord.Guild):
        return self.get_group("guild_settings")[guild.id, "track_mass_mentions"]

    def last_mass_mention_ts(self, guild: discord.Guild):
        return self.get_group("guild_settings")[guild.id, "last_mass_mention_ts"]

    def last_mass_mention_notice(self, guild: discord.Guild):
        return self.get_group("guild_settings")[guild.id, "last_mass_mention_notice"]

    def mass_mention_notice_template(self, guild: discord.Guild):
        return self.get_group("guild_settings")[guild.id, "mass_mention_notice_template"]

    async def get_guild_settings(self, guild: discord.Guild) -> GuildSettings:

        settings = {
            key_tuple[-1]: val
            async for key_tuple, val in self.backend.get_all_by_key_prefix("guild_settings", guild.id)
            if val
        }
        return GuildSettings(**settings)

    async def get_all_guild_settings(self):

        ret: defaultdict[int, GuildSettings] = defaultdict(GuildSettings)
        async for key_tuple, val in self.get_group("guild_settings").all_items():
            guild_id, setting = key_tuple
            # assertions are for type checking here
            # These are safe because the key tuples here will
            # only be sourced from the key tuples in above methods
            assert isinstance(guild_id, int)
            assert isinstance(setting, str)
            ret[guild_id] = attr.evolve(ret[guild_id], **{setting: val})
        return ret


class MentionStats(commands.Cog):
    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot
        self.storage = MentionStorage.get_store(1)
        self.guild_settings_cache: MutableMapping[int, GuildSettings] = LRU(128)
        self.sem = asyncio.Semaphore(5)

    @staticmethod
    async def remove_guild_data(guild_ids: Sequence[int]):
        store = MentionStorage.get_store(1)
        for gid in guild_ids:
            await store.backend.clear_by_key_prefix("guild_settings", gid)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not (guild := message.guild):
            return

        if not message.mention_everyone:
            # This guard may need changing in the future when other mention tracking is added
            return

        if guild.id not in self.guild_settings_cache:
            self.guild_settings_cache[guild.id] = await self.storage.get_guild_settings(guild)

        settings = self.guild_settings_cache[guild.id]

        if settings.track_mass_mentions:
            ts = int(message.created_at.timestamp())
            await self.storage.last_mass_mention_ts(guild).set_value(ts)
            self.guild_settings_cache[guild.id] = settings = attr.evolve(settings, last_mass_mention_ts=ts)

        if settings.last_mass_mention_notice:
            channel_id, message_id = settings.last_mass_mention_notice
            formatted = string.Template(settings.mass_mention_notice_template).safe_substitute(days="0 days")
            try:
                params = handle_message_parameters(content=formatted)
                await self.bot.http.edit_message(channel_id, message_id, params=params)
            except discord.NotFound:
                await self.storage.last_mass_mention_notice(guild).clear_value()
                self.guild_settings_cache[guild.id] = attr.evolve(settings, last_mass_mention_notice=None)

    @tasks.loop(hours=25)
    async def updater(self):

        all_gs = await self.storage.get_all_guild_settings()

        tasks = {
            self._update_notice(guild, settings)
            for guild_id, settings in all_gs.items()
            if (guild := self.bot.get_guild(guild_id))
        }

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _update_notice(self, guild: discord.Guild, settings: GuildSettings):

        if settings.last_mass_mention_notice:
            channel_id, message_id = settings.last_mass_mention_notice

            days = settings.days_since_last_mass_mention

            if days is None:
                return

            days_str = f"{days} days" if days != 1 else "1 day"  # let's not get into why this isn't i18n safe rn
            formatted = string.Template(settings.mass_mention_notice_template).safe_substitute(days=days_str)
            try:
                async with self.sem:
                    params=handle_message_parameters(content=formatted)
                    await self.bot.http.edit_message(channel_id, message_id, params=params)
                    await asyncio.sleep(1)
            except discord.NotFound:
                await self.storage.last_mass_mention_notice(guild).clear_value()
                self.guild_settings_cache[guild.id] = attr.evolve(settings, last_mass_mention_notice=None)

    @updater.before_loop
    async def before_updater(self):
        await self.bot.wait_until_ready()

    @admin_or_perms(manage_guild=True)
    @commands.group()
    async def mentionstatset(self, ctx: SalamanderContext):
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @commands.cooldown(1, 60, commands.BucketType.guild)
    @mentionstatset.command()
    async def createnotice(self, ctx: SalamanderContext, channel: discord.TextChannel):
        guild = ctx.guild
        assert guild
        if not channel.permissions_for(guild.me).send_messages:
            raise UserFeedbackError(custom_message="I can't send messages in that channel")
        try:
            msg = await channel.send("... (Waiting on data)")
        except Exception:
            raise UserFeedbackError(custom_message="I couldn't send that message")
        if guild.id not in self.guild_settings_cache:
            self.guild_settings_cache[guild.id] = await self.storage.get_guild_settings(guild)
        await self.storage.last_mass_mention_notice(guild).set_value([channel.id, msg.id])
        self.guild_settings_cache[guild.id] = settings = attr.evolve(
            self.guild_settings_cache[guild.id], last_mass_mention_notice=(channel.id, msg.id)
        )
        if settings.last_mass_mention_ts is None:
            ts = int(msg.created_at.timestamp())
            await self.storage.last_mass_mention_ts(guild).set_value(ts)
            self.guild_settings_cache[guild.id] = attr.evolve(
                self.guild_settings_cache[guild.id], last_mass_mention_ts=ts
            )
        await self._update_notice(guild, settings)

    @mentionstatset.command(hidden=True)
    async def daysoverride(self, ctx: SalamanderContext, days: int):
        ts = int((ctx.message.created_at - td(days=days)).timestamp())

        guild = ctx.guild
        assert guild, "implied by admin_or_perms check"

        if guild.id not in self.guild_settings_cache:
            self.guild_settings_cache[guild.id] = await self.storage.get_guild_settings(guild)

        await self.storage.last_mass_mention_ts(guild).set_value(ts)
        self.guild_settings_cache[guild.id] = settings = attr.evolve(
            self.guild_settings_cache[guild.id], last_mass_mention_ts=ts
        )
        await self._update_notice(guild, settings)

    # TODO: Allow other configuration
