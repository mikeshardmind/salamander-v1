from __future__ import annotations

import discord
from discord.ext import commands

from ...bot import HierarchyException, Salamander, SalamanderContext


def kick_sanity_check(
    bot_user: discord.Member, mod: discord.Member, target: discord.Member
):

    if target.guild.owner == target:
        raise HierarchyException(custom_message="You can't kick the owner of a guild.")

    if not mod.guild.owner == mod:
        if target.top_role == mod.top_role:
            raise HierarchyException(
                custom_message="You can't kick someone with the same top role as you."
            )

        if target.top_role > mod.top_role:
            raise HierarchyException(
                custom_message="You can't kick someone with a higher top role than you."
            )

    if not bot_user.guild.owner == bot_user:
        if target.top_role == bot_user.top_role:
            raise HierarchyException(
                custom_message="I can't kick someone with the same top role as me."
            )

        if target.top_role >= bot_user.top_role:
            raise HierarchyException(
                custom_message="I can't kick someone with a higher top role than me."
            )


class Mod(commands.Cog):
    """ Some basic mod tools """

    def __init__(self, bot: Salamander):
        self.bot = Salamander

    @commands.check_any(
        commands.is_owner(), commands.has_guild_permissions(kick_members=True)
    )  # TODO: add mod role support
    @commands.bot_has_guild_permissions(kick_members=True)
    @commands.guild_only()
    @commands.command(name="kick")
    async def kick_commnand(self, ctx: SalamanderContext, *, who: discord.Member):
        """ Kick a member without removing messages """

        kick_sanity_check(bot_user=ctx.me, mod=ctx.author, target=who)
        await who.kick(
            reacon=f"User kicked by command. (Authorizing mod: {who}({who.id})"
        )
