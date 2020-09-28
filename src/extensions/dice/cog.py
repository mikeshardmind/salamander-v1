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

from typing import TYPE_CHECKING

from discord.ext import commands

from .dicemath import DiceError, Expression

if TYPE_CHECKING:
    from ...bot import SalamanderContext
else:
    SalamanderContext = commands.Context


class Dice(commands.Cog):
    """
    Some tabletop dice.
    """

    @commands.max_concurrency(1, commands.BucketType.channel, wait=True)
    @commands.command(name="roll")
    async def roll(self, ctx: SalamanderContext, *, expression: str):
        """ Roll some dice """

        if len(expression) > 500:
            return await ctx.send("I'm not even going to try and parse that one")

        try:
            ex = Expression.from_str(expression)
            v, msg = ex.verbose_roll()
        except ZeroDivisionError:
            return await ctx.send("Oops, too many dice. I dropped them")
        except DiceError as err:
            return await ctx.send(f"{ctx.author.mention}: {err}", delete_after=15)

        prepend = (
            f"{ctx.author.mention} Results for {ex} "
            f"\N{GAME DIE} Total: {v} "
            f"\nBreakdown below"
        )
        await ctx.send_paged(msg, box=True, prepend=prepend)

    @commands.cooldown(3, 30, commands.BucketType.member)
    @commands.max_concurrency(1, commands.BucketType.channel, wait=True)
    @commands.command(name="diceinfo")
    async def rverb(self, ctx, *, expression: str):
        """
        Get info about an expression
        """

        try:
            ex = Expression.from_str(expression)
            low, high, ev = ex.get_min(), ex.get_max(), ex.get_ev()
        except ZeroDivisionError:
            return await ctx.send("Oops, too many dice. I dropped them")
        except DiceError as err:
            return await ctx.send(f"{ctx.author.mention}: {err}", delete_after=15)

        await ctx.send(
            f"Information about dice Expression: {ex}:\nLow: {low}\nHigh: {high}\nEV: {ev:.7g}"
        )
