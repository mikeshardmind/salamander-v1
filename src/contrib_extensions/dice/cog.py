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

from discord.ext import commands

from ...bot import SalamanderContext
from .dicemath import DiceError, Expression


class Dice(commands.Cog):
    """
    Some tabletop dice.
    """

    @commands.max_concurrency(1, commands.BucketType.channel, wait=True)
    @commands.command(name="roll")
    async def roll(self, ctx: SalamanderContext, *, expression: str):
        """Roll some dice"""

        if len(expression) > 500:
            return await ctx.send("I'm not even going to try and parse that one")

        try:
            ex = Expression.from_str(expression)
            msg = ex.verbose_roll2()
        except ZeroDivisionError:
            return await ctx.send("Oops, too many dice. I dropped them")
        except DiceError as err:
            return await ctx.send(f"{ctx.author.mention}: {err}", delete_after=15)

        prepend = f"{ctx.author.mention} Results for {ex} \N{GAME DIE}"
        await ctx.send_paged(msg, box=True, prepend=prepend)

    @commands.max_concurrency(1, commands.BucketType.channel, wait=True)
    @commands.command(name="multiroll")
    async def multiroll(self, ctx: SalamanderContext, times: int, *, expression: str):
        """Roll some dice"""

        if len(expression) > 500:
            return await ctx.send("I'm not even going to try and parse that one")

        if times < 1:
            return await ctx.send("Try providing a positive quantity")

        elif times > 20:
            return await ctx.send(
                "If you really need to repeat this that many times, you need to use minion/swarm/mob rules."
            )

        try:
            ex = Expression.from_str(expression)
        except DiceError as err:
            return await ctx.send(f"{ctx.author.mention}: {err}", delete_after=15)

        parts: list[str] = []

        for i in range(1, times + 1):
            try:
                msg = ex.verbose_roll2()
            except ZeroDivisionError:
                return await ctx.send("Oops, too many dice. I dropped them")
            except DiceError as err:
                return await ctx.send(f"{ctx.author.mention}: {err}", delete_after=15)

            parts.append(f"{i}.\n{msg}")

        prepend = f"{ctx.author.mention} Results for  {times}x {ex} \N{GAME DIE}"
        await ctx.send_paged("\n---\n".join(parts), box=True, prepend=prepend)

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

        await ctx.send(f"Information about dice Expression: {ex}:\nLow: {low}\nHigh: {high}\nEV: {ev:.7g}")
