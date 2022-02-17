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

from discord.ext import commands
from discord.types import embed, message, snowflake
from discord.webhook import Webhook

from ...bot import Salamander


class IPCEvents(commands.Cog, name="_hydra_helper"):
    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot

    @staticmethod
    async def send_discord_message(
        bot,
        /,
        *,
        channel_id: snowflake.Snowflake,
        content: str | None = None,
        embeds: list[embed.Embed] | None = None,
        allowed_mentions: message.AllowedMentions | None = None,
        message_reference: message.MessageReference | None = None,
    ):
        await bot.http.send_message(
            channel_id,
            content=content,
            embeds=embeds,
            allowed_mentions=allowed_mentions,
            message_reference=message_reference,
        )

    @staticmethod
    async def send_discord_webhook_message(
        bot,
        /,
        *,
        webhook_url: str,
        content: str | None = None,
        username: str | None = None,
        avatar_url: str | None = None,
        embeds: list[embed.Embed] | None = None,
        allowed_mentions: message.AllowedMentions = None,
    ):
        hook = Webhook.from_url(webhook_url, session=bot.session)
        await hook.send(
            content=content, username=username, avatar_url=avatar_url, embeds=embeds, allowed_mentions=allowed_mentions
        )  # type: ignore  # *sigh*

    routes = {
        "salamander.send_discord_message": send_discord_message,
        "salamander.send_discord_webhook_message": send_discord_webhook_message,
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
