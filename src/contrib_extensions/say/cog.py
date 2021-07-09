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

import discord
from discord.ext import commands

from ...bot import SalamanderContext, UserFeedbackError
from ...checks import mod


class Say(commands.Cog):
    """ Allows saying things as the bot. """

    #: This is a good canidate for conversion to /command later

    @mod()
    @commands.command(name="sayhere")
    async def say_here(self, ctx: SalamanderContext, *, content: str):
        """ Say something in this channel. """
        if not content:
            await ctx.send_help()
            return

        if len(content) > 2000:
            raise UserFeedbackError(custom_message="I can only send up to 2000 characters in a single message.")

        await ctx.send(content)

    @mod()
    @commands.command(name="say")
    async def say_command(self, ctx: SalamanderContext, channel: discord.TextChannel, *, content: str):
        """ Say something in a specific channel. """
        if not content:
            await ctx.send_help()
            return

        if not channel.permissions_for(ctx.guild.me).send_messages:
            raise UserFeedbackError(custom_message="I can't speak in that channel.")
        
        if len(content) > 2000:
            raise UserFeedbackError(custom_message="I can only send up to 2000 characters in a single message.")

        await channel.send(content)

    @mod()
    @commands.command(name="sayedit")
    async def edit_bot_message(self, ctx: SalamanderContext, message: discord.Message, *, content: str):
        """ Edit an existing bot message. """
        if not content:
            await ctx.send_help()
            return

        author = message.author

        if author.id != ctx.guild.me.id:
            raise UserFeedbackError(custom_message="I can't edit other people's messages.")
        
        if len(content) > 2000:
            raise UserFeedbackError(custom_message="I can only send up to 2000 characters in a single message.")

        await message.edit(content=content)
