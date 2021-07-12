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
import re
import sys
from typing import Optional, Union

import discord
from discord.ext import commands

from ...bot import Salamander, SalamanderContext, UserFeedbackError
from ...checks import admin_or_perms, guildowner_or_perms

dpy_version = discord.__version__
py_version = ".".join(f"{i}" for i in sys.version_info[:3])


class AppInfoCache:
    # TODO: Maybe move this to the bot if other things have a reason to touch this.

    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot
        self._cached_info: Optional[discord.AppInfo] = None
        self._lock = asyncio.Lock()
        self._invalidate_task: Optional[asyncio.Task] = None

    async def get_app_info(self) -> discord.AppInfo:

        async with self._lock:
            if self._cached_info is None:

                self._cached_info = await self.bot.application_info()
                if self._invalidate_task is not None:
                    self._invalidate_task.cancel()

                self._invalidate_task = asyncio.create_task(self.defered_invalidation(300))

            return self._cached_info

    async def defered_invalidation(self, time: float):
        await asyncio.sleep(time)
        async with self._lock:
            self._cached_info = None


def bot_is_public():
    """ Don't use this elsewhere. """

    async def bot_public(ctx: SalamanderContext) -> bool:
        assert isinstance(ctx.cog, Meta), "safe enough"  # nosec
        cog: Meta = ctx.cog
        info = await cog.cached_info.get_app_info()
        return info.bot_public

    return commands.check(bot_public)


class Meta(commands.Cog):
    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot
        self.cached_info = AppInfoCache(bot)

    @commands.is_owner()
    @commands.command()
    async def shutdown(self, ctx: SalamanderContext):
        """ Shuts down the bot """
        await self.bot.logout()

    @commands.command(name="info", aliases=["about"])
    async def info_com(self, ctx: SalamanderContext):
        """ Get info about this bot. """

        about_text = self.bot._behavior_flags.about_text or (
            "This bot is an instance of [Project Salamander]"
            "(https://github.com/unified-moderation-network/salamander)"
            "\nIt is considered to be stable enough for use, "
            "with lots of room to grow."
        )
        em = discord.Embed(color=ctx.me.color, description=about_text)
        em.add_field(name="Python", value=py_version)
        em.add_field(name="Discord.py", value=dpy_version)
        await ctx.send(embed=em)

    @commands.check_any(commands.is_owner(), bot_is_public())
    @commands.cooldown(1, 300, commands.BucketType.channel)
    @commands.command(name="invitelink")
    async def invite_link_command(self, ctx: SalamanderContext):
        """ Get the bot's invite link. """

        url = discord.utils.oauth_url(
            client_id=ctx.bot.user.id,
            permissions=discord.Permissions(470150262),
        )  # TODO

        await ctx.send(url)

    @admin_or_perms(manage_guild=True)
    @commands.group()
    async def prefix(self, ctx: SalamanderContext):
        """ Commands for managing the bot's prefix in this server. """
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @prefix.command(name="list")
    async def prefix_list(self, ctx: SalamanderContext):
        """ List the prefixes currently configured for this server. """

        prefixes = self.bot.prefix_manager.get_guild_prefixes(ctx.guild.id)[::-1]
        if prefixes:
            em = discord.Embed(title="Configured Prefixes", color=ctx.me.color)
            em.set_footer(text="You can also start your command by mentioning me.")
            em.description = "\n".join(f"{index}. `{prefix}`" for index, prefix in enumerate(prefixes, 1))
            await ctx.send(embed=em)
        else:
            await ctx.send("There are no configured extra prefixes in this server, but using a mention will work.")

    @prefix.command(name="add", ignore_extra=True)
    async def prefix_add(self, ctx: SalamanderContext, prefix: str):
        """
        Add a prefix.

        If you would like your prefix to end in a space, make sure you use quates.
        (Discord removes trailing whitespace from messages)

        Multi-word prefixes should also be quoted.
        """

        current_prefixes = self.bot.prefix_manager.get_guild_prefixes(ctx.guild.id)
        if len(current_prefixes) >= 5:
            raise UserFeedbackError(custom_message="You cannot configure more than 5 custom prefixes.")

        if prefix.startswith("/"):
            raise UserFeedbackError(
                custom_message=(
                    "Prefixes may not start with `/` to avoid conflicting with discord integrated /commands"
                )
            )

        for special_char_sequence in ("*", "`", "_", "~", "|", "> ", ":", "'", '"', "\\"):
            if special_char_sequence in prefix:
                raise UserFeedbackError(custom_message=f"Prefixes may not contain {special_char_sequence}")
        if prefix.startswith((f"<@{ctx.me.id}>", f"<@!{ctx.me.id}>")):
            raise UserFeedbackError(custom_message="You don't need to configure mentions as a prefix.")

        if re.search(r"<.*>", prefix):
            raise UserFeedbackError(
                custom_message="Prefixes should not contain both < and > "
                " to avoid conflicts with how Discord represents mentions internally."
            )

        if len(prefix) > 15:
            raise UserFeedbackError(custom_message="Let's not add a prefix that long.")

        self.bot.prefix_manager.add_guild_prefixes(ctx.guild.id, prefix)
        await ctx.send("Prefix added.")

    @prefix.command(name="remove", aliases=["delete"], ignore_extra=True)
    async def prefix_remove(self, ctx: SalamanderContext, prefix: str):
        """
        Remove a prefix.

        If referring to a prefix which ends in a space, make sure you use quates.
        (Discord removes trailing whitespace from messages)

        Multi-word prefixes should also be quoted.
        """
        if prefix.startswith((f"<@{ctx.me.id}>", f"<@!{ctx.me.id}>")):
            raise UserFeedbackError(custom_message="I won't remove mentioning me as a prefix")

        current_prefixes = self.bot.prefix_manager.get_guild_prefixes(ctx.guild.id)
        if prefix not in current_prefixes:
            raise UserFeedbackError(custom_message="That isn't a current prefix, so there's nothing to remove.")

        self.bot.prefix_manager.remove_guild_prefixes(ctx.guild.id, prefix)
        await ctx.send("Prefix removed.")

    @prefix_remove.error
    @prefix_add.error
    async def prefix_addremove_too_many_args(self, ctx: SalamanderContext, exc):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send(
                "I can only add one prefix at a time. If you intended that as a singular prefix, please quote it."
            )

    @admin_or_perms(manage_guild=True)
    @commands.command(name="addmod", ignore_extra=False)
    async def add_mod(self, ctx: SalamanderContext, who: discord.Member):
        """
        Add a mod.

        Mention them for best matching success.
        """

        self.bot.privlevel_manager.give_mod(ctx.guild.id, who.id)
        await ctx.send("User is considered a mod in this server.")

    @admin_or_perms(manage_guild=True)
    @commands.command(name="removemod", ignore_extra=False)
    async def rem_mod(self, ctx: SalamanderContext, who: Union[discord.Member, int]):
        """
        Remove a mod.
        """

        if isinstance(who, discord.Member):
            self.bot.privlevel_manager.remove_mod(ctx.guild.id, who.id)
        else:
            self.bot.privlevel_manager.remove_mod(ctx.guild.id, who)

        await ctx.send("If they were a mod, they aren't anymore.")

    @guildowner_or_perms(manage_guild=True)
    @commands.command(name="addadmin", ignore_extra=False)
    async def add_admin(self, ctx: SalamanderContext, who: discord.Member):
        """
        Add an admin.

        Mention them for best matching success.
        """

        self.bot.privlevel_manager.give_admin(ctx.guild.id, who.id)
        await ctx.send("User is considered an admin in this server.")

    @guildowner_or_perms(manage_guild=True)
    @commands.command(name="removeadmin", ignore_extra=False)
    async def rem_admin(self, ctx: SalamanderContext, who: Union[discord.Member, int]):
        """
        Remove an admin.
        """

        if isinstance(who, discord.Member):
            self.bot.privlevel_manager.remove_admin(ctx.guild.id, who.id)
        else:
            self.bot.privlevel_manager.remove_admin(ctx.guild.id, who)

        await ctx.send("If they were an admin, they aren't anymore.")

    @add_mod.error
    @rem_mod.error
    @add_admin.error
    @rem_admin.error
    async def add_rem_mod_admin_too_many(self, ctx, exc):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send(
                "You appeared to give me multiple users. "
                "If this isn't the case, please use quotes around "
                "their name or mention them instead."
            )

    @guildowner_or_perms(manage_guild=True)
    @commands.command(name="setadminrole", ignore_extra=False)
    async def set_adminrole(self, ctx: commands.Context, role: discord.Role):
        """
        Set the bot admin role for the server.
        """

        cursor = self.bot._conn.cursor()

        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id, admin_role)
            VALUES (?, ?)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                admin_role=excluded.admin_role
            """,
            (ctx.guild.id, role.id),
        )

        await ctx.send(f"Admin role set: {role.name}")

    @guildowner_or_perms(manage_guild=True)
    @commands.command(name="setmodrole", ignore_extra=False)
    async def set_modrole(self, ctx: commands.Context, role: discord.Role):
        """
        Set the bot mod role for the server.
        """

        cursor = self.bot._conn.cursor()

        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id, mod_role)
            VALUES (?, ?)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                mod_role=excluded.mod_role
            """,
            (ctx.guild.id, role.id),
        )

        await ctx.send(f"Mod role set: {role.name}")

    @guildowner_or_perms(manage_guild=True)
    @commands.command(name="clearadminrole", ignore_extra=False)
    async def clear_adminrole(self, ctx: commands.Context):
        """ Clears the bot admin role setting. """

        cursor = self.bot._conn.cursor()

        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id, admin_role)
            VALUES (?, ?)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                admin_role=excluded.admin_role
            """,
            (ctx.guild.id, None),
        )

        await ctx.send("Admin role setting has been reset. (None configured)")

    @guildowner_or_perms(manage_guild=True)
    @commands.command(name="clearmodrole", ignore_extra=False)
    async def clear_modrole(self, ctx: commands.Context):
        """ Clears the bot mod role setting. """

        cursor = self.bot._conn.cursor()

        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id, mod_role)
            VALUES (?, ?)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                mod_role=excluded.mod_role
            """,
            (ctx.guild.id, None),
        )

        await ctx.send("Mod role setting has been reset. (None configured)")

    @set_modrole.error
    @set_adminrole.error
    async def set_roles_too_many(self, ctx, exc):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send(
                "You appeared to give me multiple roles. "
                "If this isn't the case, please use quotes around "
                "the role name or use the role id instead."
            )
