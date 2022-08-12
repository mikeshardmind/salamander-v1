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
from discord.app_commands import Group
from discord.ext import commands


from ...bot import SalamanderContext
from .dicemath import DiceError, Expression


class Dice(commands.Cog):
    """
    Some tabletop dice.
    """

    group = Group(name="dice", description="commands for working with dice rolls")

    @group.command(name="roll", description="Roll some dice")
    async def roll(self, interaction: discord.Interaction, expression: str):
        """Roll some dice"""

        if len(expression) > 500:
            return await interaction.response.send_message("I'm not even going to try and parse that one")

        try:
            ex = Expression.from_str(expression)
            msg = ex.verbose_roll2()
        except ZeroDivisionError:
            return await interaction.response.send_message("Oops, too many dice. I dropped them")
        except DiceError as err:
            return await interaction.response.send_message(str(err))

        await interaction.response.send_message(f"```\n{msg}\n```")

    @group.command(name="secretroll", description="Roll some dice that only you can see")
    async def secretroll(self, interaction: discord.Interaction, expression: str):
        """Roll some dice"""

        if len(expression) > 500:
            return await interaction.response.send_message("I'm not even going to try and parse that one", ephemeral=True)

        try:
            ex = Expression.from_str(expression)
            msg = ex.verbose_roll2()
        except ZeroDivisionError:
            return await interaction.response.send_message("Oops, too many dice. I dropped them", ephemeral=True)
        except DiceError as err:
            return await interaction.response.send_message(str(err), ephemeral=True)

        await interaction.response.send_message(f"```\n{msg}\n```", ephemeral=True)

    @group.command(name="ev", description="Get some info about the expected value of a dice expression ")
    async def rverb(self, interaction: discord.Interaction, expression: str):
        """
        Get info about an expression
        """

        try:
            ex = Expression.from_str(expression)
            low, high, ev = ex.get_min(), ex.get_max(), ex.get_ev()
        except ZeroDivisionError:
            return await interaction.response.send_message("Oops, too many dice. I dropped them")
        except DiceError as err:
            return await interaction.response.send_message(str(err))

        await interaction.response.send_message(f"Information about dice Expression: {ex}:\nLow: {low}\nHigh: {high}\nEV: {ev:.7g}")
