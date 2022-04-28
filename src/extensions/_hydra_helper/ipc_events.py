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

"""
Leveraging the way discord.py extensions work to make the event logic more easily seperated.
"""

from __future__ import annotations
from typing import Any

import discord
from discord.ext import commands
from discord.http import handle_message_parameters

from ...bot import Salamander


class IPCEvents(commands.Cog, name="_hydra_helper"):
    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot

    @staticmethod
    async def send_discord_message(
        bot: Salamander,
        /,
        *,
        channel_id: int,
        content: str | None = None,
        embeds: list[dict] | None = None,
        allowed_mentions: dict[str, Any] | None = None,
    ):

        # TODO: fix this up

        kwargs = {
            k: v
            for k, v in (
                ("content", content),
                ("embeds", [discord.Embed.from_dict(d) for d in embeds] if embeds else []),
                ("allowed_mentions", discord.AllowedMentions(**allowed_mentions) if allowed_mentions else None),
            )
            if v
        }

        kwargs = {k: v for k, v in kwargs.items()}

        await bot.http.send_message(channel_id, params=handle_message_parameters(**kwargs))

    routes = {
        "salamander.send_discord_message": send_discord_message,
    }

    @commands.Cog.listener("on_ipc_recv")
    async def _lazy_way(self, topic, payload):
        """
        It might be better to make a route decorator that handles some of this later,
        but this will do for now and keeps it isolated enough.
        """

        try:
            method = self.routes[topic]
        except KeyError:  # There are plenty of payloads we aren't responsible for here.
            return  # nosec

        # This *can* raise a TypeError if the payload is bad. Having this be a noisy failure is a good thing
        return await method(self.bot, **payload)
