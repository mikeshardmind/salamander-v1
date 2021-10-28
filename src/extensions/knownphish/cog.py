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
from pathlib import Path
from typing import Optional


import discord
import hyperscan
from discord.ext import commands


class KnownPhish(commands.Cog):
    """
    Removes URLs Known to be in frequent use in phishing campaigns targetting discord users.
    """

    def __init__(self, bot):
        self.bot = bot
        self.db = hyperscan.Database()
        path = (Path.cwd() / __file__).with_name("patterns.list")
        with path.open(mode="r") as fp:
            expressions = {e.strip() for e in fp.readlines() if e}
        self.db.compile(
            expressions=tuple(expr.encode() for expr in expressions),
            flags=hyperscan.HS_FLAG_SOM_LEFTMOST,
        )

    @commands.Cog.listener()
    async def on_message(self, message):
        if guild := message.guild:
            channel = message.channel
            if channel.permissions_for(guild.me).manage_messages:
                if content := message.content:
                    await self.process_content(channel, message.id, message.author.id, content)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, raw_payload: discord.RawMessageUpdateEvent):

        if channel := self.bot.get_channel(raw_payload.channel_id):

            try:
                guild = channel.guild
            except AttributeError:
                return

            if channel.permissions_for(guild.me).manage_messages:
                if content := raw_payload.data.get("content", None):
                    author_id = raw_payload.data.get("author", {}).get("id", None)
                    await self.process_content(channel, raw_payload.message_id, author_id, content)

    async def process_content(
        self, channel: discord.TextChannel, message_id: int, author_id: Optional[int], content: str
    ):
        # author id is optional because discord doesn't actually guarantee it ....

        slices = []
        byt = content.encode()
        self.db.scan(byt, match_event_handler=lambda _pid, start, end, _flags, _ctx: slices.append((start, end)))

        if not slices:
            return

        await self.bot.http.delete_message(channel.id, message_id)

        user_string = f"<@{author_id}>" if author_id else "an unknown user"

        nc = bytearray(byt)
        for start, stop in slices:
            for idx in range(start, stop):
                nc[idx] = 88  # X

        defanged = nc.decode()

        await channel.send(
            f"Deleted message from {user_string} containing a potentially malicious url",
            embed=discord.Embed(title="Original (links cleaned) for context", description=defanged).set_footer(
                text="Do not access any links which are within. link cleaning is not 100%"
            ),
        )
