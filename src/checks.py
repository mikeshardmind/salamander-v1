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


# prevents commands.is_owner()
# being mixed in requiring commands.guild_only() stacked on guild checks
async def _owner_in_guild_predicate(ctx: SalamanderContext) -> bool:
    if ctx.guild:
        return await ctx.bot.is_owner(ctx.author)
    return False


def owner_in_guild():
    return commands.check(_owner_in_guild_predicate)


def _mod_predicate(ctx: SalamanderContext) -> bool:
    if ctx.guild:
        if ctx.guild.owner == ctx.author:
            return True
        return ctx.bot.privlevel_manager.member_is_mod(ctx.author)
    return False


def mod():
    return commands.check(_mod_predicate)


def _guildowner_predicate(ctx: SalamanderContext) -> bool:
    if ctx.guild:
        return ctx.author == ctx.guild.owner
    return False


def guildowner():
    return commands.check(_guildowner_predicate)


def _admin_predicate(ctx: SalamanderContext) -> bool:
    if ctx.guild:
        if ctx.guild.owner == ctx.author:
            return True
        return ctx.bot.privlevel_manager.member_is_admin(ctx.author)
    return False


def admin():
    return commands.check(_admin_predicate)


def mod_or_perms(**perms):

    commands_predicate = commands.has_guild_permissions(**perms).predicate

    async def predicate(ctx: SalamanderContext) -> bool:
        if _mod_predicate(ctx) or await _owner_in_guild_predicate(ctx):
            return True
        if perms and await commands_predicate(ctx):
            return True
        return False

    return commands.check(predicate)


def admin_or_perms(**perms):

    commands_predicate = commands.has_guild_permissions(**perms).predicate

    async def predicate(ctx: SalamanderContext) -> bool:
        if _admin_predicate(ctx) or await _owner_in_guild_predicate(ctx):
            return True
        if perms and await commands_predicate(ctx):
            return True
        return False

    return commands.check(predicate)


def guildowner_or_perms(**perms):
    commands_predicate = commands.has_guild_permissions(**perms).predicate

    async def predicate(ctx: SalamanderContext) -> bool:
        if _guildowner_predicate(ctx) or await _owner_in_guild_predicate(ctx):
            return True
        if perms and await commands_predicate(ctx):
            return True
        return False

    return commands.check(predicate)
