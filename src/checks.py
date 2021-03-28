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

from .bot import SalamanderContext


def owner_in_guild():
    # prevents commands.is_owner()
    # being mixed in requiring commands.guild_only() stacked on guild checks

    async def predicate(ctx: SalamanderContext) -> bool:
        if ctx.guild:
            return await ctx.bot.is_owner(ctx.author)
        return False

    return commands.check(predicate)


def mod():
    def predicate(ctx: SalamanderContext) -> bool:
        if ctx.guild:
            if ctx.guild.owner == ctx.author:
                return True
            return ctx.bot.privlevel_manager.member_is_mod(ctx.guild.id, ctx.author.id)
        return False

    return commands.check(predicate)


def guildowner():
    def predicate(ctx: SalamanderContext) -> bool:
        if ctx.guild:
            return ctx.author == ctx.guild.owner
        return False

    return commands.check(predicate)


def admin():
    def predicate(ctx: SalamanderContext) -> bool:
        if ctx.guild:
            if ctx.guild.owner == ctx.author:
                return True
            return ctx.bot.privlevel_manager.member_is_admin(ctx.guild.id, ctx.author.id)
        return False

    return commands.check(predicate)


def mod_or_perms(**perms):
    return commands.check_any(commands.has_guild_permissions(**perms), mod(), owner_in_guild())


def admin_or_perms(**perms):
    return commands.check_any(commands.has_guild_permissions(**perms), admin(), owner_in_guild())


def guildowner_or_perms(**perms):
    return commands.check_any(commands.has_guild_permissions(**perms), guildowner(), owner_in_guild())
