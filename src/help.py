#  This Source Code Form is subject to the terms of the Mozilla Public
#  License, v. 2.0. If a copy of the MPL was not distributed with this
#  file, You can obtain one at http://mozilla.org/MPL/2.0/.

# Original Author: https://github.com/Rapptz
# This file contains code which was copied (and modified)
# from: https://github.com/Rapptz/RoboDanny/tree/cd23371cee697d861182a037f90896d9d4a082dd

from __future__ import annotations

import asyncio
import itertools
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands, menus

if TYPE_CHECKING:
    from .bot import Salamander, SalamanderContext
else:

    class Salamander:
        """If you encounter this during introspection,
        it's a typehinting fiction to avoid a circular import."""

        pass

    class SalamanderContext:
        """If you encounter this during introspection,
        it's a typehinting fiction to avoid a circular import."""

        pass


class RoboPages(discord.ui.View):
    def __init__(
        self,
        source: menus.PageSource,
        *,
        ctx: SalamanderContext,
        check_embeds: bool = True,
        compact: bool = False,
    ):
        super().__init__()
        self.source: menus.PageSource = source
        self.check_embeds: bool = check_embeds
        self.ctx: SalamanderContext = ctx
        self.message: discord.Message | None = None
        self.current_page: int = 0
        self.compact: bool = compact
        self.input_lock = asyncio.Lock()
        self.clear_items()
        self.fill_items()

    def fill_items(self) -> None:
        if not self.compact:
            self.numbered_page.row = 1
            self.stop_pages.row = 1

        if self.source.is_paginating():
            max_pages = self.source.get_max_pages()
            use_last_and_first = max_pages is not None and max_pages >= 2
            if use_last_and_first:
                self.add_item(self.go_to_first_page)
            self.add_item(self.go_to_previous_page)
            if not self.compact:
                self.add_item(self.go_to_current_page)
            self.add_item(self.go_to_next_page)
            if use_last_and_first:
                self.add_item(self.go_to_last_page)
            if not self.compact:
                self.add_item(self.numbered_page)
            self.add_item(self.stop_pages)

    async def _get_kwargs_from_page(self, page: int) -> dict[str, Any]:
        value = await discord.utils.maybe_coroutine(self.source.format_page, self, page)
        if isinstance(value, dict):
            return value
        elif isinstance(value, str):
            return {"content": value, "embed": None}
        elif isinstance(value, discord.Embed):
            return {"embed": value, "content": None}
        else:
            return {}

    async def show_page(self, interaction: discord.Interaction, page_number: int) -> None:
        page = await self.source.get_page(page_number)
        self.current_page = page_number
        kwargs = await self._get_kwargs_from_page(page)
        self._update_labels(page_number)
        if kwargs:
            if interaction.response.is_done():
                if self.message:
                    await self.message.edit(**kwargs, view=self)
            else:
                await interaction.response.edit_message(**kwargs, view=self)

    def _update_labels(self, page_number: int) -> None:
        self.go_to_first_page.disabled = page_number == 0
        if self.compact:
            max_pages = self.source.get_max_pages()
            self.go_to_last_page.disabled = max_pages is None or (page_number + 1) >= max_pages
            self.go_to_next_page.disabled = max_pages is not None and (page_number + 1) >= max_pages
            self.go_to_previous_page.disabled = page_number == 0
            return

        self.go_to_current_page.label = str(page_number + 1)
        self.go_to_previous_page.label = str(page_number)
        self.go_to_next_page.label = str(page_number + 2)
        self.go_to_next_page.disabled = False
        self.go_to_previous_page.disabled = False
        self.go_to_first_page.disabled = False

        max_pages = self.source.get_max_pages()
        if max_pages is not None:
            self.go_to_last_page.disabled = (page_number + 1) >= max_pages
            if (page_number + 1) >= max_pages:
                self.go_to_next_page.disabled = True
                self.go_to_next_page.label = "…"
            if page_number == 0:
                self.go_to_previous_page.disabled = True
                self.go_to_previous_page.label = "…"

    async def show_checked_page(self, interaction: discord.Interaction, page_number: int) -> None:
        max_pages = self.source.get_max_pages()
        try:
            if max_pages is None:
                # If it doesn't give maximum pages, it cannot be checked
                await self.show_page(interaction, page_number)
            elif max_pages > page_number >= 0:
                await self.show_page(interaction, page_number)
        except IndexError:
            # An error happened that can be handled, so ignore it.
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id in (self.ctx.bot.owner_id, self.ctx.author.id):
            return True
        await interaction.response.send_message(
            "This pagination menu cannot be controlled by you, sorry!", ephemeral=True
        )
        return False

    async def on_timeout(self) -> None:
        if self.message:
            await self.message.edit(view=None)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        if interaction.response.is_done():
            await interaction.followup.send("An unknown error occurred, sorry", ephemeral=True)
        else:
            await interaction.response.send_message("An unknown error occurred, sorry", ephemeral=True)

    async def start(self, *, content: str | None = None) -> None:
        if self.check_embeds and not self.ctx.channel.permissions_for(self.ctx.me).embed_links:  # type: ignore
            await self.ctx.send("Bot does not have embed links permission in this channel.")
            return

        await self.source._prepare_once()
        page = await self.source.get_page(0)
        kwargs = await self._get_kwargs_from_page(page)
        if content:
            kwargs.setdefault("content", content)

        self._update_labels(0)
        self.message = await self.ctx.send(**kwargs, view=self)

    @discord.ui.button(label="≪", style=discord.ButtonStyle.grey)
    async def go_to_first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """go to the first page"""
        await self.show_page(interaction, 0)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.blurple)
    async def go_to_previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """go to the previous page"""
        await self.show_checked_page(interaction, self.current_page - 1)

    @discord.ui.button(label="Current", style=discord.ButtonStyle.grey, disabled=True)
    async def go_to_current_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def go_to_next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """go to the next page"""
        await self.show_checked_page(interaction, self.current_page + 1)

    @discord.ui.button(label="≫", style=discord.ButtonStyle.grey)
    async def go_to_last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """go to the last page"""
        # The call here is safe because it's guarded by skip_if
        await self.show_page(interaction, self.source.get_max_pages() - 1)  # type: ignore

    @discord.ui.button(label="Skip to page...", style=discord.ButtonStyle.grey)
    async def numbered_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """lets you type a page number to go to"""
        if self.input_lock.locked():
            await interaction.response.send_message("Already waiting for your response...", ephemeral=True)
            return

        if self.message is None:
            return

        async with self.input_lock:
            channel = self.message.channel
            author_id = interaction.user and interaction.user.id
            await interaction.response.send_message("What page do you want to go to?", ephemeral=True)

            def message_check(m):
                return m.author.id == author_id and channel == m.channel and m.content.isdigit()

            try:
                msg = await self.ctx.bot.wait_for("message", check=message_check, timeout=30.0)
            except asyncio.TimeoutError:
                await interaction.followup.send("Took too long.", ephemeral=True)
                await asyncio.sleep(5)
            else:
                page = int(msg.content)
                await msg.delete()
                await self.show_checked_page(interaction, page - 1)

    @discord.ui.button(label="Quit", style=discord.ButtonStyle.red)
    async def stop_pages(self, interaction: discord.Interaction, button: discord.ui.Button):
        """stops the pagination session."""
        await interaction.response.defer()
        await interaction.delete_original_message()
        self.stop()


class GroupHelpPageSource(menus.ListPageSource):
    def __init__(
        self,
        group: commands.Group | commands.Cog,
        commands: list[commands.Command],
        *,
        prefix: str,
        color: discord.Color,
    ):
        super().__init__(entries=commands, per_page=6)
        self.group: commands.Group | commands.Cog = group
        self.prefix: str = prefix
        self.color: discord.Color = color
        self.title: str = f"{self.group.qualified_name}"
        self.description: str = self.group.description

    async def format_page(self, menu: RoboPages, commands: list[commands.Command]):
        embed = discord.Embed(title=self.title, description=self.description, color=self.color)

        for command in commands:
            signature = f"{command.qualified_name} {command.signature}"
            embed.add_field(name=signature, value=command.short_doc or "No help given...", inline=False)

        maximum = self.get_max_pages()
        if maximum > 1:
            embed.set_author(name=f"Page {menu.current_page + 1}/{maximum} ({len(self.entries)} commands)")

        embed.set_footer(text=f'Use "{self.prefix}help command" for more info on a command.')
        return embed


class FieldPageSource(menus.ListPageSource):
    """A page source that requires (field_name, field_value) tuple items."""

    def __init__(self, entries, *, per_page=12):
        super().__init__(entries, per_page=per_page)
        self.embed = discord.Embed(colour=discord.Colour.blurple())

    async def format_page(self, menu, entries):
        self.embed.clear_fields()
        self.embed.description = None

        for key, value in entries:
            self.embed.add_field(name=key, value=value, inline=False)

        maximum = self.get_max_pages()
        if maximum > 1:
            text = f"Page {menu.current_page + 1}/{maximum} ({len(self.entries)} entries)"
            self.embed.set_footer(text=text)

        return self.embed


class TextPageSource(menus.ListPageSource):
    def __init__(self, text, *, prefix="```", suffix="```", max_size=2000):
        pages = commands.Paginator(prefix=prefix, suffix=suffix, max_size=max_size - 200)
        for line in text.split("\n"):
            pages.add_line(line)

        super().__init__(entries=pages.pages, per_page=1)

    async def format_page(self, menu, content):
        maximum = self.get_max_pages()
        if maximum > 1:
            return f"{content}\nPage {menu.current_page + 1}/{maximum}"
        return content


class SimplePageSource(menus.ListPageSource):
    async def format_page(self, menu, entries):
        pages = []
        for index, entry in enumerate(entries, start=menu.current_page * self.per_page):
            pages.append(f"{index + 1}. {entry}")

        maximum = self.get_max_pages()
        if maximum > 1:
            footer = f"Page {menu.current_page + 1}/{maximum} ({len(self.entries)} entries)"
            menu.embed.set_footer(text=footer)

        menu.embed.description = "\n".join(pages)
        return menu.embed


class SimplePages(RoboPages):
    """A simple pagination session reminiscent of the old Pages interface.
    Basically an embed with some normal formatting.
    """

    def __init__(self, entries, *, ctx: SalamanderContext, per_page: int = 12):
        super().__init__(SimplePageSource(entries, per_page=per_page), ctx=ctx)
        self.embed = discord.Embed(color=ctx.me.color)


class HelpSelectMenu(discord.ui.Select["HelpMenu"]):
    def __init__(self, commands: dict[commands.Cog, list[commands.Command]], bot: Salamander, color: discord.Color):
        super().__init__(
            placeholder="Select a category...",
            min_values=1,
            max_values=1,
            row=0,
        )
        self.commands: dict[commands.Cog, list[commands.Command]] = commands
        self.bot: Salamander = bot
        self.color: discord.Color = color
        self.__fill_options()

    def __fill_options(self) -> None:
        self.add_option(
            label="Index",
            emoji="\N{WAVING HAND SIGN}",
            value="__index",
            description="The help page showing how to use the bot.",
        )
        for cog, commands in self.commands.items():
            if not commands:
                continue
            description = cog.description.split("\n", 1)[0] or None
            self.add_option(label=cog.qualified_name, value=cog.qualified_name, description=description, emoji=None)

    async def callback(self, interaction: discord.Interaction):
        assert self.view is not None
        value = self.values[0]
        if value == "__index":
            await self.view.bind_to_interaction(FrontPageSource(), interaction)
        else:
            cog = self.bot.get_cog(value)
            if cog is None:
                await interaction.response.send_message("Did... did you break it?", ephemeral=True)
                return

            commands = self.commands[cog]
            if not commands:
                await interaction.response.send_message("This category appears to be empty right now.", ephemeral=True)
                return

            source = GroupHelpPageSource(cog, commands, prefix=self.view.ctx.clean_prefix, color=self.color)
            await self.view.bind_to_interaction(source, interaction)


class FrontPageSource(menus.PageSource):

    # next 3 methods are a means of forcing menu elements to be visible even as a single page
    def is_paginating(self) -> bool:
        return True

    def get_max_pages(self) -> int | None:
        return 2

    async def get_page(self, page_number: int) -> Any:
        self.index = page_number
        return self

    def format_page(self, menu: HelpMenu, page: Any):
        embed = discord.Embed(title="Help", color=menu.ctx.me.color)
        embed.description = (
            "This is the help page."
            "\nYou can use {hc_text} for help with a specific command."
            "\nYou can use {hc_text} or select an entry from the dropdown menu for help with a category."
        ).format(hc_text=f'"{menu.ctx.clean_prefix}help command"')

        embed.add_field(
            name="How to read the help",
            value="Command usage is shown with a few details. Just don't include the brackets when you use it.",
        )
        embed.add_field(name="<arg>", value="This is required", inline=False)
        embed.add_field(name="[arg]", value="This is optional", inline=False)
        embed.add_field(name="This | That", value="This or That", inline=False)
        embed.add_field(name="[arg... ]", value="This can be multiple things", inline=False)

        return embed


class HelpMenu(RoboPages):
    def __init__(self, source: menus.PageSource, ctx: SalamanderContext):
        super().__init__(source, ctx=ctx, compact=True)

    def add_categories(self, commands: dict[commands.Cog, list[commands.Command]]) -> None:
        self.clear_items()
        self.add_item(HelpSelectMenu(commands, self.ctx.bot, color=self.ctx.me.color))
        self.fill_items()

    async def bind_to_interaction(self, source: menus.PageSource, interaction: discord.Interaction) -> None:
        self.source = source
        self.current_page = 0

        await self.source._prepare_once()
        page = await self.source.get_page(0)
        kwargs = await self._get_kwargs_from_page(page)
        self._update_labels(0)
        await interaction.response.edit_message(**kwargs, view=self)


class PaginatedHelpCommand(commands.HelpCommand):
    context: SalamanderContext

    def __init__(self):
        super().__init__(
            command_attrs={
                "cooldown": commands.CooldownMapping.from_cooldown(1, 5.0, commands.BucketType.member),
                "help": "Shows help about the bot, a command, or a category",
            }
        )

    async def on_help_command_error(self, ctx: SalamanderContext, error: commands.CommandError):
        """We don't want to do anything here... yet."""
        pass

    def get_command_signature(self, command: commands.Command) -> str:
        parent = command.full_parent_name
        if len(command.aliases) > 0:
            aliases = "|".join(command.aliases)
            fmt = f"[{command.name}|{aliases}]"
            if parent:
                fmt = f"{parent} {fmt}"
            alias = fmt
        else:
            alias = command.name if not parent else f"{parent} {command.name}"
        return f"{alias} {command.signature}"

    async def send_bot_help(self, mapping):
        bot = self.context.bot

        def key(command) -> str:
            cog = command.cog
            return cog.qualified_name if cog else ""

        entries: list[commands.Command] = await self.filter_commands(bot.commands, sort=True, key=key)

        all_commands: dict[commands.Cog, list[commands.Command]] = {}
        for name, children in itertools.groupby(entries, key=key):
            if name == "":
                continue

            cog = bot.get_cog(name)
            assert cog is not None
            all_commands[cog] = sorted(children, key=lambda c: c.qualified_name)

        menu = HelpMenu(FrontPageSource(), ctx=self.context)
        menu.add_categories(all_commands)
        await menu.start()

    async def send_cog_help(self, cog):
        entries = await self.filter_commands(cog.get_commands(), sort=True)
        menu = HelpMenu(
            GroupHelpPageSource(cog, entries, prefix=self.context.clean_prefix, color=self.context.me.color),
            ctx=self.context,
        )
        await menu.start()

    def common_command_formatting(self, embed_like, command):
        embed_like.title = self.get_command_signature(command)
        if command.description:
            embed_like.description = f"{command.description}\n\n{command.help}"
        else:
            embed_like.description = command.help or "No help found..."

    async def send_command_help(self, command):
        # No pagination necessary for a single command.
        embed = discord.Embed(color=self.context.me.color)
        self.common_command_formatting(embed, command)
        await self.context.send(embed=embed)

    async def send_group_help(self, group):
        subcommands = group.commands
        if len(subcommands) == 0:
            return await self.send_command_help(group)

        entries = await self.filter_commands(subcommands, sort=True)
        if len(entries) == 0:
            return await self.send_command_help(group)

        source = GroupHelpPageSource(group, entries, prefix=self.context.clean_prefix, color=self.context.me.color)
        self.common_command_formatting(source, group)
        menu = HelpMenu(source, ctx=self.context)
        await menu.start()
