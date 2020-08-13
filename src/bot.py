from __future__ import annotations

import asyncio
import io
import logging
import re
import sys
from collections import Counter
from types import TracebackType
from typing import Awaitable, Callable, List, Optional, Type, TypeVar
from uuid import uuid4

import discord
from discord.ext import commands

from .config import BasicConfig, Prefixes
from .ipc_layer import ZMQHandler
from .utils import only_once, pagify

log = logging.getLogger("salamander")

BASALISK_GAZE = "basalisk.gaze"
BASALISK_OFFER = "basalisk.offer"


__all__ = ["setup_logging", "Salamander", "SalamanderContext"]


@only_once
def setup_logging():
    log = logging.getLogger("salamander")
    handler = logging.StreamHandler(sys.stdout)
    rotating_file_handler = logging.handlers.RotatingFileHandler(
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


class SalamanderContext(commands.Context):

    bot: "Salamander"

    def __init__(self, **kwargs):
        super.__init__(**kwargs)
        self.pool = None
        self.conn = None

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]] = None,
        exc_value: Optional[BaseException] = None,
        traceback: Optional[TracebackType] = None,
    ):
        await self.aclose()

    async def aclose(self):
        pass

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
    base = bot.__prefixes.data.get(msg.guild.id, ()) if msg.guild else ()
    return commands.when_mentioned_or(*base)


class Salamander(commands.Bot):
    def __init__(self, *args, **kwargs):
        self.__prefixes = Prefixes()
        self.__close_queue = asyncio.Queue()  # type: asyncio.Queue[Awaitable[...]]
        self.__background_loop: Optional[asyncio.Task] = None
        self.__conf = BasicConfig()
        super().__init__(*args, command_prefix=_prefix)
        # spam handling

        # DEP-WARN: commands.CooldownMapping.from_cooldown
        self.__global_cooldown = commands.CooldownMapping.from_cooldown(
            8, 20, commands.BucketType.user
        )
        self.__spam_counter = Counter()
        self.__zmq: ZMQHandler()
        self.__zmq_task: Optional[asyncio.Task] = None

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

        this_uuid = uuid4().int

        def matches(*args) -> bool:
            topic, (recv_uuid, *_data) = args
            return topic == BASALISK_GAZE and recv_uuid == this_uuid

        # This is an intentionally genererous timeout, won't be an issue.
        fut = self.wait_for("ipc_recv", check=matches, timeout=5)
        self.ipc_send(BASALISK_OFFER, ((this_uuid, None), string))
        try:
            await fut
        except asyncio.TimeoutError:
            return False
        else:
            return True

    def ipc_send(self, topic, payload):
        self.__zmq.push(topic, payload)

    def start_zmq(self, zmq):

        if self.__zmq_task is not None:
            return

        async def zmq_injest_task():
            await self.wait_until_ready()
            async with self.__zmq as zmq_handler:
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
        self.__close_queue.put_nowait(f)

    async def __closing_loop(self):
        """ Handle things get put in queue to be async closed from sync contexts """

        while True:
            awaitable = await self.__close_queue.get()
            try:
                await awaitable
            except Exception as exc:
                log.exception(
                    "Unhandled exception while closing resource", exc_info=exc
                )
            finally:
                self.__close_queue.task_done()

    async def __aenter__(self):
        await self.__prepare()
        return self

    async def __prepare(self):
        self.__background_loop = asyncio.create_task(self.__closing_loop())

    async def aclose(self):
        if self.__background_loop is not None:
            self.__background_loop.cancel()
            await self.__background_loop

        if self.__zmq_task is not None:
            self.__zmq_task.cancel()
            await self.__zmq_task

        await self.__close_queue.join()

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]] = None,
        exc_value: Optional[BaseException] = None,
        traceback: Optional[TracebackType] = None,
    ) -> None:
        await self.aclose()

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

        if self.__conf.user_is_blocked(ctx.author.id):
            return

        if ctx.guild and self.__conf.guild_is_blocked(ctx.guild.id):
            return

        if not await self.is_owner(ctx.author):
            author_id = ctx.author.id
            # DEP-WARN: commands.CooldownMapping.update_rate_limit
            retry = self.__global_cooldown.update_rate_limit(ctx.message)
            if retry:
                self.__spam_counter[author_id] += 1
                if self.__spam_counter[author_id] > 3:
                    await self.__conf.block_user(author_id)
                    log.info(
                        "User: {user_id} has been blocked temporarily for "
                        "hitting the global ratelimit a lot.",
                        user_id=author_id,
                    )
                return
            else:
                self.__spam_counter.pop(author_id, None)

        async with ctx:
            await ctx.invoke()
