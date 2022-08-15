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
import io
import linecache
import logging
import re
import signal
import sys
import traceback
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Sequence, TypeVar
from uuid import uuid4

import apsw
import attr
import discord
from discord.ext import commands
from lru import LRU

from .ipc_layer import ZMQHandler
from .modlog import ModlogHandler
from .utils import MainThreadSingletonMeta, format_list, only_once, pagify

try:
    import uvloop
except ImportError:
    uvloop = None


log = logging.getLogger("salamander")

BASILISK_GAZE = "basilisk.gaze"
BASILISK_OFFER = "basilisk.offer"


__all__ = ["Salamander", "SalamanderContext", "get_third_party_data_path", "get_contrib_data_path"]

_CUSTOM_DATA_DIR: ContextVar[str | None] = ContextVar("DATA_DIR", default=None)


impl = sys.implementation.name


if hasattr(sys, "pyston_version_info"):
    # If they change this as a detection method after how big a deal they made of this and what I've had to fix this week already...
    raise RuntimeError(
        """
        Pyston is not supported.

        There are some practical reasons not to support it related to native code and JIT use in this project.
        If you would like to see pyston support, please indicate as much on the issue tracker.
        I won't guarantee it will happen, but I'll at least have some feedback without it coming from a more serious issue.

        I have chosen to have this fail early in a predictable way now, than to possibly have it break during operation in unepected ways.
        """
        # pyston would not work anyway due to minimum python version *currently*
        # but I'd rather not run into this later, unexpectedly, forgetting about it.
        # I've already had pyston cause issues in another closed-source project utilizing native code
        # that had guards for non-cpython use and fallbacks to pure python with a warning about performance.
        # pyston maintainers don't like code like the below* and won't aknowledge that there are reasons for it,
        # instead trying to shift the blame on the ecosystem,
        # or say that we should really be using something else for this like feature flags (that doesn't exist yet)
        # While I agree that the current solution is not ideal,
        # actively rejecting it before having a better option in place just makes the situation worse, and seems to
        # be self-serving to increase adoption, leaning on "well, most things are compatible"
        # and hand-waving away the cases where they are not.
        # * || Taken from maintainer comment in issue about this https://github.com/pyston/pyston/issues/39
        ## if implementation == "CPython":
        ##     doNormalThing()
        ## elif implementation == "PyPy":
        ##     doSpecialPyPyThing()
        ## else:
        ##    raise Exception("not supported")
    )


if impl == "pypy":
    raise RuntimeError(
        """
        PyPy is not currently supported. This is due to incompatibility with apsw and hyperscan.
        If you would like to see support for PyPy, please open an issue.
        If this incompatibility no longer exists and this warning is still here, please also open an issue.
        """
    )
    # I'm not including `numba` in the list of incompatibilities,
    # as falling back to pure python code on pypy would be acceptible where it is used.


elif impl != "cpython":
    raise RuntimeError(
        """
        The implementation of python you are using has not been tested for
        compatibility with native and JIT code used in this project.

        I have chosen to have this fail early in a predictable way now, than to possibly have it break during operation in unepected ways.

        If you would like to see support for it, please open an issue with details
        about the implementation and version of python you are using
        """
    )


@attr.s(auto_attribs=True, frozen=True, kw_only=True)
class ExtensionManifest:
    required_bot_perms: int
    authors: list[str]
    url: str | None = None
    top_level_command_names: list[str]
    cog_names: list[str]
    license_info: str
    data_retention_description: str
    version: str | None = None
    remove_user_data: Callable[[Sequence[int]], Awaitable]
    remove_guild_data: Callable[[Sequence[int]], Awaitable]

    @staticmethod
    async def no_removal_handling_required(_ids: Sequence[int]):
        ...


def get_third_party_data_path(extension_name: str) -> Path:

    base = get_data_path() / "third_party_data"
    base.mkdir(exist_ok=True, parents=True)

    p = (base / extension_name).resolve()
    if p.parent != base:
        raise RuntimeError("Really? name your extension something filesystem safe.")

    p.mkdir(exist_ok=True)
    return p


def get_contrib_data_path(extension_name: str) -> Path:

    base = get_data_path() / "third_party_data"
    base.mkdir(exist_ok=True, parents=True)

    p = (base / extension_name).resolve()
    if p.parent != base:
        raise RuntimeError("Really? name your extension something filesystem safe.")

    p.mkdir(exist_ok=True)
    return p


def get_data_path() -> Path:
    if base := _CUSTOM_DATA_DIR.get():
        base_path = Path(base).resolve()
        if not base_path.is_dir():
            raise RuntimeError("Provided non-directory data path")
    else:
        base_path = Path.cwd()

    return base_path


@only_once
def setup_logging(nofile: bool = False) -> None:
    log = logging.getLogger("salamander")
    log.setLevel(logging.INFO)
    if __debug__:
        log.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        style="%",
    )

    handler.setFormatter(formatter)
    log.addHandler(handler)

    if not nofile:

        rotating_file_handler = RotatingFileHandler(
            get_data_path() / "salamander.log", maxBytes=10000000, backupCount=5
        )
        # Log appliance use in future with aiologger.
        rotating_file_handler.setFormatter(formatter)
        log.addHandler(rotating_file_handler)


@only_once
def add_connection_hooks() -> None:
    def setwal(connection):
        connection.cursor().execute(
            """
            PRAGMA journal_mode = wal;
            PRAGMA synchronous = NORMAL;
            PRAGMA foreign_keys=ON;
            """
        )
        connection.wal_autocheckpoint(1000)

    if setwal not in apsw.connection_hooks:
        apsw.connection_hooks.append(setwal)


class SalamanderException(Exception):
    """Base Exception for custom Exceptions"""

    custom_message: str
    reset_cooldown: bool


class IncompleteInputError(SalamanderException):
    """To be used when a command did not recieve all the inputs"""

    def __init__(self, *args, reset_cooldown: bool = False, custom_message: str = ""):
        super().__init__("Incomplete user input")
        self.reset_cooldown: bool = reset_cooldown
        self.custom_message: str = custom_message


class HierarchyException(SalamanderException):
    """For cases where invalid targetting due to hierarchy occurs"""

    def __init__(self, *args, custom_message: str = ""):
        super().__init__("Hierarchy memes")
        self.custom_message: str = custom_message
        self.reset_cooldown: bool = False


class UserFeedbackError(SalamanderException):
    """Generic error which propogates a message to the user"""

    def __init__(self, *args, custom_message: str):
        super().__init__(self, custom_message)
        self.custom_message = custom_message
        self.reset_cooldown: bool = False


_PT = TypeVar("_PT", bound=str)

UNTIMELY_RESPONSE_ERROR_STR = "I'm not waiting forever for a response (exiting)."

NON_TEXT_RESPONSE_ERROR_STR = "There doesn't appear to be any text in your response, please try this command again."

INVALID_OPTION_ERROR_FMT = "That wasn't a valid option, please try this command again.\n(Valid options are: {})"


class YesNoView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__()
        self.value: bool | None = None
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.value = True
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.value = False
        self.stop()


_LT = TypeVar("_LT", discord.Embed, str, covariant=True)


class ListMenuView(discord.ui.View):
    def __init__(self, user_id: int, listmenu: list[_LT], *, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.listmenu = listmenu
        self.index = 0
        self.message: discord.Message | None = None

    def setup_by_current_index(self) -> discord.Embed | str:
        ln = len(self.listmenu)
        self.index %= ln
        self.previous.disabled = self.jump_first.disabled = bool(self.index == 0)
        self.nxt.disabled = self.jump_last.disabled = bool(self.index == ln - 1)
        return self.listmenu[self.index]

    async def start(self, destination: discord.abc.Messageable):
        element = self.setup_by_current_index()

        if isinstance(element, discord.Embed):
            self.message = await destination.send(embed=element, view=self)
        else:
            self.message = await destination.send(element, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def edit_to_current_index(self, interaction: discord.Interaction):
        element = self.setup_by_current_index()

        message = interaction.message

        if message is None:
            log.error("What the fuck, interaction without a message??")
            raise

        if isinstance(element, discord.Embed):
            await message.edit(embed=element, view=self)
        else:
            await message.edit(content=element, view=self)

    @discord.ui.button(label="<<", style=discord.ButtonStyle.gray)
    async def jump_first(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.index = 0
        await self.edit_to_current_index(interaction)

    @discord.ui.button(label="<", style=discord.ButtonStyle.gray)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.index -= 1
        await self.edit_to_current_index(interaction)

    @discord.ui.button(label=">", style=discord.ButtonStyle.gray)
    async def nxt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.index += 1
        await self.edit_to_current_index(interaction)

    @discord.ui.button(label=">>", style=discord.ButtonStyle.gray)
    async def jump_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.index = -1
        await self.edit_to_current_index(interaction)


class SalamanderContext(commands.Context["Salamander"]):

    bot: Salamander

    @property
    def clean_prefix(self) -> str:
        repl = f"@{self.me.display_name}".replace("\\", r"\\")
        pattern = re.compile(rf"<@!?{self.me.id}>")
        assert self.prefix is not None, "typechecking madness"
        return pattern.sub(repl, self.prefix)

    async def list_menu(
        self,
        pages: list[_LT],
        *,
        timeout: float = 180,
        alt_destination: discord.abc.Messageable | None = None,
        delete_on_return: bool = False,
    ):
        view = ListMenuView(self.author.id, pages, timeout=timeout)
        await view.start(alt_destination or self)
        await view.wait()
        if message := view.message:
            if delete_on_return:
                await message.delete()
            else:
                await message.edit(view=None)

    async def yes_or_no(
        self,
        prompt: str,
        timeout: float = 30,
        reset_cooldown_on_failure: bool = False,
        delete_on_return: bool = False,
    ) -> bool:

        view = YesNoView(self.author.id)
        sent = await self.send(prompt, view=view)
        await asyncio.wait({view.wait()}, timeout=timeout)
        view.stop()

        if view.value is None:
            raise IncompleteInputError(
                custom_message=UNTIMELY_RESPONSE_ERROR_STR,
                reset_cooldown=reset_cooldown_on_failure,
            )

        try:
            return view.value
        finally:
            if delete_on_return:
                await sent.delete()
            else:
                await sent.edit(view=None)

    async def send_paged(
        self,
        content: str,
        *,
        box: bool = False,
        prepend: str | None = None,
        page_size: int = 1800,
        allowed_mentions: discord.AllowedMentions | None = None,
    ):
        """Send something paged out"""

        for i, page in enumerate(pagify(content, page_size=page_size)):
            if box:
                page = f"```\n{page}\n```"
            if i == 0 and prepend:
                page = f"{prepend}\n{page}"
            await self.send(page, allowed_mentions=allowed_mentions)

    async def safe_send(self, content: str, **kwargs):
        if kwargs.pop("file", None):
            raise TypeError("Safe send is incompatible with sending a file.")

        if len(content) <= 2000:
            return await self.send(content, **kwargs)

        fp = io.BytesIO(content.encode())
        return await self.send(file=discord.File(fp, filename="message.txt"), **kwargs)


def _prefix(bot: Salamander, msg: discord.Message) -> list[str]:
    guild = msg.guild
    base = bot.prefix_manager.get_guild_prefixes(guild.id) if guild else ()
    return commands.when_mentioned_or(*base)(bot, msg)


class BehaviorFlags:
    """
    Contains info about which external services are expected
    and which extensions are to be loaded initially.

    (To be used by a configuration parser of some sort in the future: TODO)
    """

    def __init__(
        self,
        *,
        no_basilisk: bool = False,
        no_serpent: bool = False,
        initial_exts: Sequence[str] = (),
        disable_all_message_commands: bool = False,
        disable_replaced_message_commands: bool = False,
        enable_slash_commands: bool = False,
    ):
        self.disable_all_message_commands: bool = disable_all_message_commands
        self.disable_replaced_message_commands: bool = disable_replaced_message_commands
        self.enable_slash_commands: bool = enable_slash_commands
        self.no_basilisk: bool = no_basilisk
        self.no_serpent: bool = no_serpent
        self.initial_exts: Sequence[str] = initial_exts

    @classmethod
    def defaults(cls):
        """
        Factory method for the defaults.

        The defaults are not guaranteed to be unchanging.
        """

        exts = (
            "src.contrib_extensions.dice",
            "src.contrib_extensions.qotw",
            "src.extensions.annoyancefilters",
            "src.extensions.cleanup",
            "src.extensions.feedback",
            "src.extensions.filter",
            "src.extensions.knownphish",
            "src.extensions.meta",
            "src.extensions.mod",
            "src.extensions.modnotes",
            "src.extensions.rolemanagement",
        )

        return cls(no_serpent=True, initial_exts=exts)


class PrefixManager(metaclass=MainThreadSingletonMeta):
    def __init__(self, bot: Salamander):
        self._bot: Salamander = bot
        self._cache = LRU(128)

    def get_guild_prefixes(self, guild_id: int) -> Sequence[str]:
        base = self._cache.get(guild_id, None)
        if base is not None:
            return base

        cursor = self._bot._conn.cursor()
        res = tuple(
            pfx
            for (pfx,) in cursor.execute(
                """
                SELECT prefix FROM guild_prefixes
                WHERE guild_id=?
                ORDER BY prefix DESC
                """,
                (guild_id,),
            )
        )
        self._cache[guild_id] = res
        return res

    def add_guild_prefixes(self, guild_id: int, *prefixes: str):
        cursor = self._bot._conn.cursor()
        with self._bot._conn:

            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (guild_id,),
            )

            cursor.executemany(
                """
                INSERT INTO guild_prefixes (guild_id, prefix)
                VALUES (?, ?)
                ON CONFLICT (guild_id, prefix) DO NOTHING
                """,
                tuple((guild_id, pfx) for pfx in prefixes),
            )

        # Extremely likely to be cached already
        try:
            del self._cache[guild_id]
        except KeyError:
            pass

    def remove_guild_prefixes(self, guild_id: int, *prefixes: str):
        cursor = self._bot._conn.cursor()
        with self._bot._conn:

            cursor.executemany(
                """
                DELETE FROM guild_prefixes WHERE guild_id=? AND prefix=?
                """,
                tuple((guild_id, pfx) for pfx in prefixes),
            )

        # Extremely likely to be cached already
        try:
            del self._cache[guild_id]
        except KeyError:
            pass


class BlockManager(metaclass=MainThreadSingletonMeta):
    def __init__(self, bot: Salamander):
        self._bot: Salamander = bot

    def guild_is_blocked(self, guild_id: int) -> bool:
        cursor = self._bot._conn.cursor()
        for row in cursor.execute(
            """
            SELECT is_blocked from guild_settings
            WHERE guild_id =?
            """,
            (guild_id,),
        ):
            return row[0]
        return False

    def _modify_guild_block(self, val: bool, guild_id: int):
        cursor = self._bot._conn.cursor()
        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id, is_blocked)
            VALUES (?, ?)
            ON CONFLICT (guild_id)
            DO UPDATE SET is_blocked=excluded.is_blocked
            """,
            (guild_id, val),
        )

    def block_guild(self, guild_id: int):
        self._modify_guild_block(True, guild_id)

    def unblock_guild(self, guild_id: int):
        self._modify_guild_block(False, guild_id)

    def user_is_blocked(self, user_id: int) -> bool:
        cursor = self._bot._conn.cursor()
        for row in cursor.execute(
            """
            SELECT is_blocked from user_settings
            WHERE user_id = ?
            """,
            (user_id,),
        ):
            return row[0]
        return False

    def member_is_blocked(self, guild_id: int, user_id: int) -> bool:
        cursor = self._bot._conn.cursor()
        for row in cursor.execute(
            """
            SELECT is_blocked from member_settings
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ):
            return row[0]
        return False

    def _modify_user_block(self, val: bool, user_ids: Sequence[int]):
        cursor = self._bot._conn.cursor()
        with self._bot._conn:
            cursor.executemany(
                """
                INSERT INTO user_settings (user_id, is_blocked)
                VALUES (?, ?)
                ON CONFLICT (user_id) DO UPDATE SET
                    is_blocked=excluded.is_blocked
                """,
                tuple((uid, val) for uid in user_ids),
            )

    def _modify_member_block(self, val: bool, guild_id: int, user_ids: Sequence[int]):
        cursor = self._bot._conn.cursor()
        with self._bot._conn:
            cursor.executemany(
                """
                INSERT INTO user_settings (user_id)
                VALUES (?)
                ON CONFLICT (user_id) DO NOTHING
                """,
                tuple((uid,) for uid in user_ids),
            )
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id)
                VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (guild_id,),
            )
            cursor.executemany(
                """
                INSERT INTO member_settings (guild_id, user_id, is_blocked)
                VALUES (?, ?, ?)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    is_blocked=excluded.is_blocked
                """,
                tuple((guild_id, uid, val) for uid in user_ids),
            )

    def block_users(self, *user_ids: int):
        self._modify_user_block(True, user_ids)

    def unblock_users(self, *user_ids: int):
        self._modify_user_block(False, user_ids)

    def block_members(self, guild_id: int, *user_ids: int):
        self._modify_member_block(True, guild_id, user_ids)

    def unblock_members(self, guild_id: int, *user_ids: int):
        self._modify_member_block(False, guild_id, user_ids)


class PrivHandler(metaclass=MainThreadSingletonMeta):
    def __init__(self, bot: Salamander):
        self._bot: Salamander = bot

    def member_is_mod(self, member: discord.Member | discord.User) -> bool:
        if not isinstance(member, discord.Member):
            return False
        cursor = self._bot._conn.cursor()
        cursor.execute(
            """
            SELECT is_mod OR is_admin
            FROM member_settings
            WHERE guild_id = ? and user_id = ?
            """,
            (member.guild.id, member.id),
        )
        r = cursor.fetchone()

        if r and r[0]:
            return True

        cursor.execute(
            """
            SELECT mod_role, admin_role
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (member.guild.id,),
        )
        r = cursor.fetchone()

        if r:
            for role_id in r:
                if role_id and member._roles.has(role_id):
                    return True

        return False

    def member_is_admin(self, member: discord.Member | discord.User) -> bool:
        if not isinstance(member, discord.Member):
            return False
        cursor = self._bot._conn.cursor()
        cursor.execute(
            """
            SELECT is_admin
            FROM member_settings
            WHERE guild_id = ? and user_id = ?
            """,
            (member.guild.id, member.id),
        )
        r = cursor.fetchone()

        if r and r[0]:
            return True

        r = cursor.execute(
            """
            SELECT admin_role
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (member.guild.id,),
        )
        r = cursor.fetchone()

        if r and r[0]:
            if member._roles.has(r[0]):
                return True

        return False

    def _modify_mod_status(self, val: bool, guild_id: int, user_ids: Sequence[int]):
        cursor = self._bot._conn.cursor()
        with self._bot._conn:

            cursor.executemany(
                """
                INSERT INTO user_settings (user_id) VALUES (?)
                ON CONFLICT (user_id) DO NOTHING
                """,
                tuple((uid,) for uid in user_ids),
            )
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id)
                VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (guild_id,),
            )
            cursor.executemany(
                """
                INSERT INTO member_settings (guild_id, user_id, is_mod)
                VALUES (?,?,?)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET is_mod=excluded.is_mod
                """,
                tuple((guild_id, uid, val) for uid in user_ids),
            )

    def _modify_admin_status(self, val: bool, guild_id: int, user_ids: Sequence[int]):
        cursor = self._bot._conn.cursor()
        with self._bot._conn:
            cursor.executemany(
                """
                INSERT INTO user_settings (user_id)
                VALUES (?)
                ON CONFLICT (user_id) DO NOTHING
                """,
                tuple((uid,) for uid in user_ids),
            )
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id)
                VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (guild_id,),
            )
            cursor.executemany(
                """
                INSERT INTO member_settings (guild_id, user_id, is_admin)
                VALUES (?,?,?)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET is_admin=excluded.is_admin
                """,
                tuple((guild_id, uid, val) for uid in user_ids),
            )

    def give_mod(self, guild_id: int, *user_ids: int):
        self._modify_mod_status(True, guild_id, user_ids)

    def remove_mod(self, guild_id: int, *user_ids: int):
        self._modify_mod_status(False, guild_id, user_ids)

    def give_admin(self, guild_id: int, *user_ids: int):
        self._modify_admin_status(True, guild_id, user_ids)

    def remove_admin(self, guild_id: int, *user_ids: int):
        self._modify_admin_status(False, guild_id, user_ids)


class Salamander(commands.AutoShardedBot):
    def __init__(self, *args, **kwargs):
        self._behavior_flags: BehaviorFlags = kwargs.pop("behavior", None) or BehaviorFlags.defaults()
        super().__init__(
            *args,
            command_prefix=_prefix,
            description="Project Salamander",
            help_command=None,
            **kwargs,
        )

        self._zmq = ZMQHandler()
        self._zmq_task: asyncio.Task | None = None
        db_path = get_data_path() / "salamander.db"
        self._conn = apsw.Connection(str(db_path))
        self.modlog: ModlogHandler = ModlogHandler(self._conn)
        self.prefix_manager: PrefixManager = PrefixManager(self)
        self.block_manager: BlockManager = BlockManager(self)
        self.privlevel_manager: PrivHandler = PrivHandler(self)

    async def __aenter__(self) -> Salamander:
        await super().__aenter__()

        # TODO: Figure out which stuff here I want to move to setup_hook (this predates)

        for ext in dict.fromkeys(self._behavior_flags.initial_exts):
            # TODO: make this less hard-coded and have extensions be able to specify requirements for load.
            if ext == "src.extensions.filter" and self._behavior_flags.no_basilisk:
                continue
            await self.load_extension(ext)

        if not self._behavior_flags.no_basilisk:
            await self.load_extension("src.extensions._hydra_helper")

        if self._zmq_task is None:

            async def zmq_injest_task() -> None:
                await self.wait_until_ready()
                async with self._zmq as zmq_handler:
                    while True:
                        topic, payload = await zmq_handler.get()
                        self.dispatch("ipc_recv", topic, payload)

            self._zmq_task = asyncio.create_task(zmq_injest_task())

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ):
        if self._zmq_task is not None:
            self._zmq_task.cancel()
            self._zmq_task = None

        await super().__aexit__(exc_type, exc_value, traceback)

    async def on_command_error(self, ctx: SalamanderContext, exc: Exception):

        if isinstance(exc, commands.CommandNotFound):
            return
        elif isinstance(exc, commands.MissingRequiredArgument):
            pass
        elif isinstance(exc, commands.NoPrivateMessage):
            await ctx.author.send("This command cannot be used in private messages.")
        elif isinstance(exc, commands.UserInputError):
            if exc.args and (msg := exc.args[0]):
                await ctx.send(msg)
        elif isinstance(exc, commands.CommandInvokeError):
            original = exc.original
            if isinstance(original, SalamanderException):
                if original.reset_cooldown:
                    if ctx.command:
                        ctx.command.reset_cooldown(ctx)
                if original.custom_message:
                    await ctx.send_paged(original.custom_message)
            elif not isinstance(original, (discord.HTTPException, commands.TooManyArguments)):
                # too many arguments should be handled on an individual basis
                # it requires enabling ignore_extra=False (default is True)
                # and the user facing message should be tailored to the situation.
                # HTTP exceptions should never hit this logger from a command (faulty command)
                if ctx.command:
                    log.exception(f"In {ctx.command.qualified_name}:", exc_info=original)

    async def check_basilisk(self, string: str) -> bool:
        """
        Check whether or not something should be filtered

        This offloads work to the shared filtering process.

        The default is no response, it's assumed to be fine.

        This prevents other features specific to this
        component from failing over if basilisk is not in use or in a failed state.
        Status checks of other components will be handled later on.

        If anything blocks the loop for longer than the timeout,
        it's possible that false negatives can occur,
        but if anything blocks the loop for that long, there are larger issues.
        """

        if self._behavior_flags.no_basilisk:
            return False

        this_uuid = uuid4().bytes

        def matches(*args) -> bool:
            topic, (recv_uuid, *_data) = args
            return topic == BASILISK_GAZE and recv_uuid == this_uuid

        # This is an intentionally genererous timeout, won't be an issue.
        fut = self.wait_for("ipc_recv", check=matches, timeout=5)
        self.ipc_put(BASILISK_OFFER, ((this_uuid, None), string))
        try:
            await fut
        except asyncio.TimeoutError:
            return False
        else:
            return True

    def ipc_put(self, topic: str, payload: Any) -> None:
        """
        Put something in a queue to be sent via IPC
        """
        self._zmq.put(topic, payload)

    def member_is_considered_muted(self, member: discord.Member) -> bool:
        """
        Checks if a user has a mute entry in the database
        *or* has the muted role for the guild

        You should not modify the roles of members outside
        of muting/unmuting for whom this returns true
        """

        cursor = self._conn.cursor()
        guild = member.guild
        cursor.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM guild_mutes
                WHERE guild_id = ? AND user_id = ?
            )
            """,
            (guild.id, member.id),
        )

        if (row := cursor.fetchone()) and row[0]:
            return True

        cursor.execute(
            """
            SELECT mute_role FROM guild_settings WHERE guild_id = ?
            """,
            (guild.id,),
        )
        row = cursor.fetchone()

        if row:
            mute_role_id = row[0]
            if mute_role_id and member._roles.has(mute_role_id):
                return True

        return False

    async def get_context(
        self, message: discord.Message, *, cls: type[SalamanderContext] = SalamanderContext
    ) -> SalamanderContext:
        return await super().get_context(message, cls=cls)

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        await self.process_commands(message)

    async def process_commands(self, message: discord.Message):
        if self._behavior_flags.disable_all_message_commands:
            return
        try:
            await asyncio.wait_for(self.wait_until_ready(), timeout=5)
        except asyncio.TimeoutError:
            return
        ctx = await self.get_context(message, cls=SalamanderContext)

        if ctx.command is None:
            return

        if self.block_manager.user_is_blocked(message.author.id):
            return

        if ctx.guild:
            if TYPE_CHECKING:
                #: These are lies, but correct enough
                assert isinstance(ctx.channel, (discord.TextChannel, discord.Thread))
                assert isinstance(ctx.me, discord.Member)

            if self.block_manager.member_is_blocked(ctx.guild.id, message.author.id):
                return

            if not ctx.channel.permissions_for(ctx.me).send_messages:
                if TYPE_CHECKING:
                    # This is a lie, and TODO: fix d.py typing.
                    assert isinstance(ctx.author, discord.User)
                if await self.is_owner(ctx.author):
                    await ctx.author.send("Hey, I don't even have send perms in that channel.")
                return

        await self.invoke(ctx)

    async def close(self):
        await super().close()
        # do not remove, allows graceful disconnects.
        await asyncio.sleep(1)

    @classmethod
    def run_with_wrapping(cls, token: str, config=None, no_file_log: bool = False):
        """
        This wraps all asyncio behavior

        Don't use this with manual control of the loop as a requirement.
        """

        setup_logging(nofile=no_file_log)
        add_connection_hooks()
        if uvloop is not None:
            uvloop.install()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.add_signal_handler(signal.SIGINT, lambda: loop.stop())
            loop.add_signal_handler(signal.SIGTERM, lambda: loop.stop())
        except NotImplementedError:
            pass

        async def runner():

            intents = discord.Intents.all()
            intents.dm_typing = False
            intents.guild_typing = False

            instance = cls(
                intents=intents,
                behavior=config,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False),
            )

            try:
                async with instance:
                    await instance.start(token, reconnect=True)
            finally:
                if not instance.is_closed():
                    await instance.close()

        def stop_when_done(fut):
            loop.stop()

        fut = asyncio.ensure_future(runner(), loop=loop)
        try:
            fut.add_done_callback(stop_when_done)
            loop.run_forever()
        except KeyboardInterrupt:
            log.warning("Please don't shut the bot down by keyboard interrupt")
        finally:
            fut.remove_done_callback(stop_when_done)
            # allow outstanding non-discord tasks a brief moment to clean themselves up
            loop.run_until_complete(asyncio.sleep(0.05))

            tasks: set[asyncio.Task] = {t for t in asyncio.all_tasks(loop) if not t.done()}
            for t in tasks:
                if not t.get_name().startswith("waterfall.finalizer"):
                    # Waterfalls should be allowed to clean up.
                    # If these tasks are already in progress because the waterfall was closing before we
                    # reached cancellation here, we should (try to) allow them to finish.
                    t.cancel()

            # as an implementation detail, any canceled tasks don't actually cancel until the event loop cycles to them
            # asyncio.sleep(0) causes an async context switch (good)
            # but is also considered complete at the same time.
            loop.run_until_complete(asyncio.sleep(0))

            # At this point, anything that wasn't excluded from cancellation should be properly cancelled.
            # While we want to allow pending tasks the time they need to finish, there's a practical upper limit on this.

            async def limited_finalization():
                done, pending = await asyncio.wait(tasks, timeout=3)

                if not pending:
                    log.debug("Clean shutdown accomplished.")
                    return

                # done, pending should both be sets of tasks here,
                # asyncio.wait uses ensure_future for wrapping which returns futures unchanged.
                # tasks are instances of futures.
                # all below task method use should be safe.

                if log.getEffectiveLevel() > logging.DEBUG:
                    # If we're running in production,
                    # We really just want to log indicator of issue and
                    # issue location and continue as graceful a shutdown as possible.
                    for task in pending:
                        name = task.get_name()
                        coro = task.get_coro()
                        log.warning("Task %s wrapping coro %r did not exit properly", name, coro)
                else:

                    for task in pending:
                        name = task.get_name()
                        coro = task.get_coro()

                        # The below is a realtively optimized way to get details about each frame
                        # in the task's stack

                        # List of tuple per frame, tuple in form: (filename, lineno, name, line)
                        # This is for use with traceback.StackSummary.from_list
                        extracted_list = []
                        # used to prevent extra calls to linecache.checkcache
                        checked = set()

                        for f in task.get_stack():
                            lineno = f.f_lineno
                            co = f.f_code
                            filename = co.co_filename
                            name = co.co_name
                            # Using linecache here as it's the way the standard lib
                            # accesses the same info when it needs it, and is optimized as such.
                            if filename not in checked:
                                checked.add(filename)
                                linecache.checkcache(filename)
                            line = linecache.getline(filename, lineno, f.f_globals)
                            extracted_list.append((filename, lineno, name, line))

                        log.warning("Task %s wrapping coro %r did not exit properly", name, coro)
                        if extracted_list:
                            stack = traceback.StackSummary.from_list(extracted_list).format()
                            log.debug(
                                "Task %r wrapping coro %r stack info:\n%s",
                                name,
                                coro,
                                stack,
                            )

            if tasks:
                loop.run_until_complete(limited_finalization())

            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())

            for task in tasks:
                try:
                    if (exc := task.exception()) is not None:
                        loop.call_exception_handler(
                            {
                                "message": "Unhandled exception in task during shutdown.",
                                "exception": task.exception(),
                                "task": exc,
                            }
                        )
                except (asyncio.InvalidStateError, asyncio.CancelledError):
                    pass

            asyncio.set_event_loop(None)
            loop.close()

        if not fut.cancelled():
            try:
                return fut.result()
            except KeyboardInterrupt:
                return None
