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

from datetime import timedelta

from discord.ext import commands

from ...bot import SalamanderContext
from ...checks import mod_or_perms


class Cleanup(commands.Cog):
    """ Quick message cleanup """

    @commands.bot_has_guild_permissions(manage_messages=True)
    @mod_or_perms(manage_messages=True)
    @commands.command()
    async def cleanup(self, ctx: SalamanderContext, number_or_strategy: int):
        """ Cleanup some messages """  # TODO: strategy support

        if number_or_strategy > 100:
            confirm = await ctx.prompt(
                f"Are you sure you want to delete up to {number_or_strategy} messages?",
                options=("yes", "no"),
                timeout=30,
                delete_on_return=True,
            )
            if confirm == "no":
                return

        # I think waterfall use might make sense here? IDK --Liz
        # Maybe, but I get the feeling it won't feel responsive enough. -- Sinbad

        to_delete = [ctx.message]

        cutoff = ctx.message.created_at - timedelta(days=10)

        # Strategy might go in params here
        # Don't use after param, changes API behavior. Can add oldest_first=False,
        # but this will increase the needed underlying api calls.
        async for message in ctx.history(limit=number_or_strategy, before=ctx.message):
            # Strategy support goes here

            if message.created_at < cutoff:
                break

            to_delete.append(message)

            if len(to_delete) == 100:
                await ctx.channel.delete_messages(to_delete)
                to_delete = []

        if to_delete:
            if len(to_delete) == 1:
                # Why does discord's API care about this?
                await to_delete[0].delete()
            else:
                await ctx.channel.delete_messages(to_delete)
