from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import signal
import sys
from collections import Counter
from logging.handlers import RotatingFileHandler
from types import TracebackType
from typing import Awaitable, Callable, List, Optional, Type, TypeVar
from uuid import uuid4

try:
    import uvloop
except ImportError:
    uvloop = None

try:
    import jishaku
except ImportError:
    jishaku = None

import discord
from discord.ext import commands

from .cogs import FilterDemo, Meta
from .config import BasicConfig, Prefixes
from .ipc_layer import ZMQHandler
from .utils import cancel_all_tasks, only_once, pagify

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


class SalamanderContext(commands.Context):

    bot: "Salamander"

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
    base = bot._prefixes.data.get(msg.guild.id, ()) if msg.guild else ()
    return commands.when_mentioned_or(*base)(bot, msg)


class Salamander(commands.Bot):
    def __init__(self, *args, **kwargs):
        self._prefixes = Prefixes()
        self._close_queue = asyncio.Queue()  # type: asyncio.Queue[Awaitable[...]]
        self._background_loop: Optional[asyncio.Task] = None
        self._conf = BasicConfig()
        super().__init__(*args, command_prefix=_prefix, **kwargs)
        # spam handling

        # DEP-WARN: commands.CooldownMapping.from_cooldown
        self.__global_cooldown = commands.CooldownMapping.from_cooldown(
            8, 20, commands.BucketType.user
        )
        self._spam_counter = Counter()
        self._zmq = ZMQHandler()
        self._zmq_task: Optional[asyncio.Task] = None

        self.add_cog(FilterDemo(self))
        self.add_cog(Meta(self))
        if jishaku is not None:
            self.load_extension("jishaku")

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

    async def __aenter__(self):
        await self.__prepare()
        return self

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

        if self._conf.user_is_blocked(ctx.author.id):
            return

        if ctx.guild and self._conf.guild_is_blocked(ctx.guild.id):
            return

        if ctx.guild:
            if not ctx.channel.permissions_for(ctx.me).send_messages:
                if await self.is_owner(ctx.author):
                    await ctx.author.send(
                        "Hey, I don't even have send perms in that channel."
                    )
                return

        if not await self.is_owner(ctx.author):
            author_id = ctx.author.id
            # DEP-WARN: commands.CooldownMapping.update_rate_limit
            retry = self.__global_cooldown.update_rate_limit(ctx.message)
            if retry:
                self._spam_counter[author_id] += 1
                if self._spam_counter[author_id] > 3:
                    await self._conf.block_user(author_id)
                    log.info(
                        "User: {user_id} has been blocked temporarily for "
                        "hitting the global ratelimit a lot.",
                        user_id=author_id,
                    )
                return
            else:
                self._spam_counter.pop(author_id, None)

        async with ctx:
            await self.invoke(ctx)

    @classmethod
    def run_with_wrapping(cls, token, *args, **kwargs):
        """
        This wraps all asyncio behavior

        Don't use this with manual control of the loop as a requirement.
        """

        setup_logging()

        if uvloop is not None:
            uvloop.install()

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            instantiated = cls(*args, **kwargs)

            async def runner():
                async with instantiated as bot_object:
                    try:
                        await bot_object.start(token)
                    finally:
                        await bot_object.logout()

            if os.name != "nt":
                signals = (
                    signal.SIGHUP,  # pylint: disable=no-member
                    signal.SIGTERM,
                    signal.SIGINT,
                )
                for s in signals:
                    loop.add_signal_handler(
                        s, lambda s=s: asyncio.create_task(instantiated.logout())
                    )

            def stop_when_done(f: asyncio.Future):
                loop.stop()

            fut = loop.create_task(runner())
            fut.add_done_callback(stop_when_done)

            loop.run_forever()
        except KeyboardInterrupt:
            log.warning("Exiting from keyboard interrupt")
            loop.run_until_complete(instantiated.logout())
        finally:
            try:
                fut.remove_done_callback(stop_when_done)
                cancel_all_tasks(loop)
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(asyncio.sleep(1))
            finally:
                if not fut.cancelled():  # normal exit
                    return fut.result()
