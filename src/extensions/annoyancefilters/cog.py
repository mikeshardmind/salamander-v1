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
from typing import NamedTuple

import discord
from discord.ext import commands
from lru import LRU

from ...bot import SalamanderContext
from ...checks import admin_or_perms

# left in it's own file for peace of source code
from .emoji_constants import DISCORD_EMOJIS

EMOJI_REGEX = re.compile("|".join(re.escape(s) for s in DISCORD_EMOJIS))

# Discord doesn't do anything clever and check attachment mime type,
# renaming a .png to .nothing will result in it uploaded without an attempt at render.
# as the rendered form is the one with potential for abuse/annoyance,
# it's the only one we're checking for.

APNG_FILENAME_REGEX = re.compile(r"\.a?png$")


class GuildSettings(NamedTuple):
    mods_immune: bool = False
    admins_immune: bool = False
    remove_apngs: bool = False
    remove_excessive_html_elements: bool = False

    @classmethod
    def recommended(cls):
        return cls(False, True, True, True)

    def to_dict(self, guild_id: int):
        return {
            "mods_immmune": self.mods_immune,
            "admins_immune": self.admins_immune,
            "remove_apngs": self.remove_apngs,
            "remove_exessive_html_elements": self.remove_excessive_html_elements,
            "guild_id": guild_id,
        }


class AnnoyanceFilters(commands.Cog):
    """ Filter out content which is poorly behaved on Discord """

    def __init__(self, bot):
        self.bot = bot
        self._settings_cache = LRU(1024)

    def get_guild_settings(self, guild_id: int) -> GuildSettings:

        if r := self._settings_cache.get(guild_id, None):
            return r

        cursor = self.bot._conn.cursor()

        res = cursor.execute(
            """
            SELECT mods_immune, admins_immune, remove_apngs, remove_excessive_html_elements
            FROM annoyance_filter_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        ).fetchone()

        cursor.close()

        self._settings_cache[guild_id] = settings = GuildSettings(*res) if res else GuildSettings()
        return settings

    def set_guild_settings(self, guild_id: int, settings: GuildSettings):

        self._settings_cache[guild_id] = settings

        cursor = self.bot._conn.cursor()
        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id) VALUES (:guild_id)
                ON CONFLICT (guild_id) DO NOTHING;
            INSERT INTO annoyance_filter_settings (
                guild_id, mods_immune, admins_immune, remove_apngs, remove_excessive_html_elements
            ) VALUES (:guild_id, :mods_immune, :admins_immune, :remove_apngs, :remove_excessive_html_elements);
            """,
            settings.to_dict(guild_id),
        )

        cursor.close()

    def check_excessive_elements(self, content: str) -> bool:
        """
        This is a quick check to determine if a message likely has over 200 html elements when rendered in client.
        This causes unwanted behaior, including allowing hiding content (such as mentions).

        This check may under report currently. This is a lazy approach to start,
        a more robust one may replace this later if deemed neccessary.

        This is a discord issue, but the reality is it is something that has been abused.
        """

        emoji_count = len(EMOJI_REGEX.findall(content))
        content_length = len(content)
        escaped_length = len(discord.utils.escape_markdown(content))
        num_nodes = emoji_count + (escaped_length - content_length) / 2
        return num_nodes >= 200

    async def check_attachments_for_apngs(self, *attachments: discord.Attachment) -> bool:
        """
        Discord doesn't animate apngs, this leads to people abusing them.

        This is only geared toward checking attachments at this point in time.

        At a later date, when more settings for the bot owner are added
        we may be able to scan link previews,
        but I'm not adding it until we have some owner
        settings regarding fetching end user controlled links.
        """

        for attachment in attachments:
            if APNG_FILENAME_REGEX.search(attachment.filename):
                # https://wiki.mozilla.org/APNG_Specification#.60fdAT.60:_The_Frame_Data_Chunk
                # We aren't checking for png validity, but the presence of the frame data chunk
                # is enough to be sure it isn't a normal, non-animated, valid png
                if b"fdAT" in (await attachment.read()):
                    return True

        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not (guild := message.guild):
            return

        if not message.channel.permissions_for(message.guild.me).manage_messages:
            return

        settings = self.get_guild_settings(guild.id)

        if (settings.mods_immune and self.bot.priv_handler.member_is_mod(message.author)) or (
            settings.admins_immune and self.bot.priv_handler.member_is_admin(message.author)
        ):
            return

        if settings.remove_excessive_html_elements:
            if message.content and self.check_excessive_elements(message.content):
                await message.delete()
                return

        if settings.remove_apngs:
            if message.attachments and await self.check_attachments_for_apngs(*message.attachments):
                await message.delete()
                return

    @commands.Cog.listener()
    async def on_raw_message_edit(self, raw_payload: discord.RawMessageUpdateEvent):

        if not (channel := self.bot.get_channel(raw_payload.channel_id)):
            return

        try:
            guild = channel.guild
        except AttributeError:
            return

        if not channel.permissions_for(guild.me).manage_messages:
            return

        if content := raw_payload.data.get("content", None):
            settings = self.get_guild_settings(guild.id)
            if settings.remove_excessive_html_elements and self.check_excessive_elements(content):

                member_id = raw_payload.data.get("member", {}).get("id", None)
                member = guild.get_member(member_id) if member_id else None
                if not member:
                    await self.bot.http.delete_message(channel.id, raw_payload.message_id)

                if not (
                    (settings.mods_immune and self.bot.priv_handler.member_is_mod(member))
                    or (settings.admins_immune and self.bot.priv_handler.member_is_admin(member))
                ):
                    await self.bot.http.delete_message(channel.id, raw_payload.message_id)

    @admin_or_perms(manage_messages=True, manage_guild=True)
    @commands.group(name="annoyancefilter")
    async def top_level_group(self, ctx: SalamanderContext):
        """ Configuration for various annoyances. """

        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @top_level_group.command(name="enablerecommended")
    async def enable_recommended(self, ctx: SalamanderContext):
        """Quickly enable the recommended filter settings:

        The recommended settings are to filter out messages from non-admins (mods not exempt)
        that contain too many markdown elements for discord to display properly or that
        have attachments which view differently in the browser than they do in discord
        due to discord not animating animated png files
        """

        self.set_guild_settings(ctx.guild.id, GuildSettings.recommended())
        await ctx.send("Now using the recommended settings.")

    @top_level_group.command(name="disable")
    async def disable(self, ctx: SalamanderContext):
        """ Disable annoyance filtering for this server. """

        self.set_guild_settings(ctx.guild.id, GuildSettings())
        await ctx.send("No longer filtering for annoyances.")

    @top_level_group.command(name="view")
    async def view_settings(self, ctx: SalamanderContext):
        """ Get info about the current settings. """

        settings = self.get_guild_settings(ctx.guild.id)

        if not (settings.remove_apngs or settings.remove_excessive_html_elements):
            await ctx.send("Filtering for discord specific issues with content is not enabled in this server.")
            return

        parts = []
        if settings.remove_apngs and settings.remove_excessive_html_elements:
            parts.append(
                "Currently filtering messages that may contain hidden content due "
                "to a long time discord bug and messages which may have attachemnts "
                "that view differently in browser and in discord due to discord not animating apng files."
            )

        elif settings.remove_apngs:
            parts.append("Currently filtering messages that may contain hidden content due to a long time discord bug.")

        elif settings.remove_excessive_html_elements:
            parts.append(
                "Currently filtering messages which may have attachemnts "
                "that view differently in browser and in discord due to discord not animating apng files."
            )

        if settings.mods_immune and settings.admins_immune:
            parts.append("Mods and admins are exempt from this filtering behavior.")
        elif settings.admins_immune:
            parts.append("Admins are exempt from this filtering behavior.")
        elif settings.mods_immune:  # We probably shouldn't ever hit this branch
            parts.append("Mods are exempt from this filtering behavior.")
        else:
            parts.append("Mods and admins are not exempt from this filtering behavior.")

        await ctx.send(" ".join(parts))

    @top_level_group.command(name="custom")
    async def interactive(self, ctx: SalamanderContext):
        """ Set up filtering with an interactive prompt. """

        elements = await ctx.yes_or_no(
            "Discord hides portions of messages if they contain "
            "too many formatting characters or too many emojis. "
            "This can allow pings to be hidden from moderators in "
            "messages or just be at a threshold where the client may lag for some users. "
            "\n\nWould you like to enable automatic removal of messages like this? "
            "(Options are yes/no)"
        )

        apng = await ctx.yes_or_no(
            "When animated pngs are uploaded to Discord, discord only shows the first frame. "
            "When these images are opened in the browser or downloaded, "
            "the png will play to the last frame and either loop or stop depending on the image. "
            "Some users have used this in ways that can range from annoying to malicious, "
            "but there are also legitimate uses for apng files."
            "\n\nWould you like to enable detection and removal of messages with apngs attached? "
            "(options are yes/no)"
        )

        if not (elements or apng):

            self.set_guild_settings(ctx.guild.id, GuildSettings())
            await ctx.send("Ok, that's all of the available annoyance filters at this time.")
            return

        admins = await ctx.yes_or_no("Would you like admins to be exempt from these filters? (options are yes/no)")

        if admins:

            mods = await ctx.yes_or_no("Would you like mods to also be exempt? (options are yes/no)")

        else:
            mods = False

        self.set_guild_settings(
            ctx.guild.id,
            GuildSettings(
                remove_excessive_html_elements=elements,
                remove_apngs=apng,
                admins_immune=admins,
                mods_immune=mods,
            ),
        )

        await ctx.send("Filtering has been set up.")
