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
import io
import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from typing import Awaitable, Callable, List, Optional, Sequence, Type, TypeVar
from uuid import uuid4

try:
    import uvloop
except ImportError:
    uvloop = None

import apsw
import discord
from discord.ext import commands
from lru import LRU

from .ipc_layer import ZMQHandler
from .modlog import ModlogHandler
from .utils import MainThreadSingletonMeta, format_list, only_once, pagify

log = logging.getLogger("salamander")

BASALISK_GAZE = "basalisk.gaze"
BASALISK_OFFER = "basalisk.offer"


__all__ = ["setup_logging", "Salamander", "SalamanderContext"]


@only_once
def setup_logging():
    log = logging.getLogger("salamander")
    handler = logging.StreamHandler(sys.stdout)
    rotating_file_handler = RotatingFileHandler(
        "salamander.log", maxBytes=10000000, backupCount=5
    )
    # Log appliance use in future with aiologger.
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        style="%",
    )
    handler.setFormatter(formatter)
    rotating_file_handler.setFormatter(formatter)
    log.addHandler(handler)
    log.addHandler(rotating_file_handler)


class SalamanderException(Exception):
    """ Base Exception for custom Exceptions """

    custom_message: str

    @property
    def reset_cooldown(self) -> bool:
        return False


class IncompleteInputError(SalamanderException):
    """ To be used when a command did not recieve all the inputs """

    def __init__(self, *args, reset_cooldown: bool = False, custom_message: str = ""):
        super().__init__("Incomplete user input")
        self.reset_cooldown: bool = reset_cooldown
        self.custom_message: str = custom_message


class HierarchyException(SalamanderException):
    """ For cases where invalid targetting due to hierarchy occurs """

    def __init__(self, *args, custom_message: str = ""):
        super().__init__("Hierarchy memes")
        self.custom_message: str = custom_message


class UserFeedbackError(SalamanderException):
    """ Generic error which propogates a message to the user """

    def __init__(self, *args, custom_message: str):
        super().__init__(self, custom_message)
        self.custom_message = custom_message


_PT = TypeVar("_PT", bound=str)

UNTIMELY_RESPONSE_ERROR_STR = "I'm not waiting forever for a response (exiting)."

NON_TEXT_RESPONSE_ERROR_STR = (
    "There doesn't appear to be any text in your response, "
    "please try this command again."
)

INVALID_OPTION_ERROR_FMT = (
    "That wasn't a valid option, please try this command again."
    "\n(Valid options are: {})"
)


class SalamanderContext(commands.Context):

    bot: Salamander

    @property
    def clean_prefix(self) -> str:
        repl = f"@{self.me.display_name}".replace("\\", r"\\")
        pattern = re.compile(rf"<@!?{self.me.id}>")
        return pattern.sub(repl, self.prefix)

    async def send_help(self, command=None):
        """
        An opinionated choice that ctx.send_help()
        should default to help based on the current command
        """
        command = command or self.command
        await super().send_help(command)

    async def prompt(
        self,
        prompt: str,
        *,
        options: Sequence[_PT],
        timeout: float,
        case_sensitive: bool = False,
        reset_cooldown_on_failure: bool = False,
    ) -> _PT:
        """
        Prompt for a choice, raising an error if not matching
        """

        def check(m: discord.Message) -> bool:
            return m.author.id == self.author.id and m.channel.id == self.channel.id

        #  bot.wait_for adds to internal listeners, returning an awaitable
        #  This ordering is desirable as we can ensure we are listening
        #  before asking, but have the timeout apply after we've sent
        #  (avoiding a (user perspective) inconsistent timeout)
        fut = self.bot.wait_for("message", check=check, timeout=timeout)
        await self.send(prompt)
        try:
            response = await fut
        except asyncio.TimeoutError:
            raise IncompleteInputError(
                custom_message=UNTIMELY_RESPONSE_ERROR_STR,
                reset_cooldown=reset_cooldown_on_failure,
            )

        if response.content is None:
            # did they upload an image as a response?
            raise IncompleteInputError(
                custom_message=NON_TEXT_RESPONSE_ERROR_STR,
                reset_cooldown=reset_cooldown_on_failure,
            )

        content = response.content if case_sensitive else response.content.casefold()

        if content not in options:
            raise IncompleteInputError(
                custom_message=INVALID_OPTION_ERROR_FMT.format(format_list(options)),
                reset_cooldown=reset_cooldown_on_failure,
            )

        return content

    async def send_paged(
        self,
        content: str,
        *,
        box: bool = False,
        prepend: Optional[str] = None,
        page_size: int = 1800,
    ):
        """ Send something paged out """

        for i, page in enumerate(pagify(content, page_size=page_size)):
            if box:
                page = f"```\n{page}\n```"
            if i == 0 and prepend:
                page = f"{prepend}\n{page}"
            await self.send(page)

    async def safe_send(self, content: str, **kwargs):
        if kwargs.pop("file", None):
            raise TypeError("Safe send is incompatible with sending a file.")
        if len(content) > 2000:
            fp = io.BytesIO(content.encode())
            return await self.send(
                file=discord.File(fp, filename="message.txt"), **kwargs
            )
        else:
            return await self.send(content, **kwargs)


_CT = TypeVar("_CT", bound=SalamanderContext)


def _prefix(
    bot: "Salamander", msg: discord.Message
) -> Callable[["Salamander", discord.Message], List[str]]:
    guild = msg.guild
    base = bot.prefix_manager.get_guild_prefixes(guild.id) if guild else ()
    return commands.when_mentioned_or(*base)(bot, msg)


class BehaviorFlags:
    """
    Class for setting extra behavior
    mostly when relating to IPC services which may not be running.

    This isn't exposed to construction of the bot yet. (TODO)
    """

    def __init__(self, *, no_basalisk: bool = False, no_serpent: bool = False):
        self.no_basalisk: bool = no_basalisk
        self.no_serpent: bool = no_serpent


class PrefixManager(metaclass=MainThreadSingletonMeta):
    def __init__(self, bot: Salamander):
        self._bot: Salamander = bot
        self._cache = LRU(128)

    def get_guild_prefixes(self, guild_id: int) -> Sequence[str]:
        base = self._cache.get(guild_id, ())
        if base:
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
                ON CONFLICT (guild_id) DO NOTHING
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

            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (guild_id,),
            )

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

    def user_is_blocked(self, user_id: int) -> bool:
        cursor = self._bot._conn.cursor()
        r = cursor.execute(
            """
            SELECT is_blocked from user_settings
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if r:
            return r[0]
        return False

    def member_is_blocked(self, guild_id: int, user_id: int) -> bool:
        cursor = self._bot._conn.cursor()
        r = cursor.execute(
            """
            SELECT is_blocked from member_settings
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ).fetchone()
        if r:
            return r[0]
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

    def member_is_mod(self, guild_id: int, user_id: int) -> bool:
        cursor = self._bot._conn.cursor()
        r = cursor.execute(
            """
            SELECT is_mod OR is_admin
            FROM member_settings
            WHERE guild_id = ? and user_id = ?
            """,
            (guild_id, user_id),
        ).fetchone()

        return r[0] if r else False

    def member_is_admin(self, guild_id: int, user_id: int) -> bool:
        cursor = self._bot._conn.cursor()
        r = cursor.execute(
            """
            SELECT is_admin
            FROM member_settings
            WHERE guild_id = ? and user_id = ?
            """,
            (guild_id, user_id),
        ).fetchone()

        return r[0] if r else False

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
                DO UPDATE SET is_admin=excluded.is_mod
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


class Salamander(commands.Bot):
    def __init__(self, *args, **kwargs):
        self._close_queue = asyncio.Queue()  # type: asyncio.Queue[Awaitable[...]]
        self._background_loop: Optional[asyncio.Task] = None
        # TODO: ensure filter can be enabled per server before this rolls out.
        self._behavior_flags: BehaviorFlags = BehaviorFlags(
            no_basalisk=True, no_serpent=True
        )
        super().__init__(*args, command_prefix=_prefix, **kwargs)

        self._zmq = ZMQHandler()
        self._zmq_task: Optional[asyncio.Task] = None

        self._conn = apsw.Connection("salamander.db")

        self.modlog: ModlogHandler = ModlogHandler(self._conn)
        self.prefix_manager: PrefixManager = PrefixManager(self)
        self.block_manager: BlockManager = BlockManager(self)
        self.privlevel_manager: PrivHandler(self)

        self.load_extension("jishaku")
        self.load_extension("src.contrib_extensions.dice")
        self.load_extension("src.extensions.mod")
        self.load_extension("src.extensions.meta")
        self.load_extension("src.extensions.filter")

    async def on_command_error(self, ctx: SalamanderContext, exc: Exception):
        if isinstance(exc, commands.NoPrivateMessage):
            await ctx.author.send("This command cannot be used in private messages.")
        elif isinstance(exc, commands.CommandInvokeError):
            original = exc.original
            if isinstance(original, SalamanderException):
                if original.reset_cooldown:
                    ctx.command.reset_cooldown(ctx)
                if original.custom_message:
                    await ctx.send_paged(original.custom_message)
            elif not isinstance(
                original, (discord.HTTPException, commands.TooManyArguments)
            ):
                # too many arguments should be handled on an individual basis
                # it requires enabling ignore_extra=False (default is True)
                # and the user facing message should be tailored to the situation.
                log.exception(f"In {ctx.command.qualified_name}:", exc_info=original)
        elif isinstance(exc, commands.ArgumentParsingError):
            await ctx.send(exc)

    async def check_basalisk(self, string: str) -> bool:
        """
        Check whether or not something should be filtered

        This offloads work to the shared filtering process.

        The default is no response, it's assumed to be fine.

        This prevents other features specific to this
        component from failing over if basalisk is not in use or in a failed state.
        Status checks of other components will be handled later on.

        If anything blocks the loop for longer than the timeout,
        it's possible that false negatives can occur,
        but if anything blocks the loop for that long, there are larger issues.
        """

        if self._behavior_flags.no_basalisk:
            return False

        this_uuid = uuid4().bytes

        def matches(*args) -> bool:
            topic, (recv_uuid, *_data) = args
            return topic == BASALISK_GAZE and recv_uuid == this_uuid

        # This is an intentionally genererous timeout, won't be an issue.
        fut = self.wait_for("ipc_recv", check=matches, timeout=5)
        self.ipc_put(BASALISK_OFFER, ((this_uuid, None), string))
        try:
            await fut
        except asyncio.TimeoutError:
            return False
        else:
            return True

    def ipc_put(self, topic, payload):
        """
        Put something in a queue to be sent via IPC
        """
        self._zmq.put(topic, payload)

    def start_zmq(self):

        if self._zmq_task is not None:
            return

        async def zmq_injest_task():
            await self.wait_until_ready()
            async with self._zmq as zmq_handler:
                while True:
                    topic, payload = await zmq_handler.get()
                    self.dispatch("ipc_recv", topic, payload)

        self.__zmq_task = asyncio.create_task(zmq_injest_task())

    def submit_for_finalizing_await(self, f: Awaitable):
        """
        Intended for finalizing async resources from sync contexts.

        Awaitable provided should handle it's own exceptions

        >>> submit_for_finalizing_await(aiohttp_clientsession.close())
        """
        self._close_queue.put_nowait(f)

    async def _closing_loop(self):
        """ Handle things get put in queue to be async closed from sync contexts """

        while True:
            awaitable = await self._close_queue.get()
            try:
                await awaitable
            except Exception as exc:
                log.exception(
                    "Unhandled exception while closing resource", exc_info=exc
                )
            finally:
                self._close_queue.task_done()

    async def __prepare(self):
        self.start_zmq()
        if self._background_loop is None:
            self._background_loop = asyncio.create_task(self._closing_loop())

    async def start(self, *args, **kwargs):
        await self.__prepare()
        await super().start(*args, **kwargs)

    async def close(self):
        await self.aclose()
        await super().close()

    async def aclose(self):
        if self._background_loop is not None:
            self._background_loop.cancel()
            await self._background_loop
            self._background_loop = None

        if self._zmq_task is not None:
            self._zmq_task.cancel()
            await self._zmq_task
            self._zmq_task = None

        await self._close_queue.join()

    async def get_context(
        self, message: discord.Message, *, cls: Type[_CT] = SalamanderContext
    ) -> _CT:
        return await super().get_context(message, cls=cls)

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        await self.process_commands(message)

    async def process_commands(self, message: discord.Message):
        ctx = await self.get_context(message, cls=SalamanderContext)

        if ctx.command is None:
            return

        if self.block_manager.user_is_blocked(message.author.id):
            return

        if ctx.guild:

            if self.block_manager.member_is_blocked(ctx.guild.id, message.author.id):
                return

            if not ctx.channel.permissions_for(ctx.me).send_messages:
                if await self.is_owner(ctx.author):
                    await ctx.author.send(
                        "Hey, I don't even have send perms in that channel."
                    )
                return

        await self.invoke(ctx)

    @classmethod
    def run_with_wrapping(cls, token):
        """
        This wraps all asyncio behavior

        Don't use this with manual control of the loop as a requirement.
        """

        setup_logging()

        if uvloop is not None:
            uvloop.install()

        intents = discord.Intents(
            guilds=True,
            # below might be settable to False if we require mentioning users in moderation actions.
            # This then means the bot can scale with fewer barriers
            # (mentioned users contain roles in message objects allowing proper hierarchy checks)
            # It's also needed if we allow reaction removals to trigger actions...
            # Or if we want to resolve permissions accurately per channel....
            members=True,
            # This is only needed for live bansync, consider if that's something we want and either uncomment or remove
            # Known downside: still requires fetch based sync due to no guarantee of event delivery.
            #  bans=True,
            voice_states=True,
            guild_messages=True,
            guild_reactions=True,
            dm_messages=True,
            dm_reactions=True,
        )

        instance = cls(
            intents=intents,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
        )

        instance.run(token, reconnect=True)
