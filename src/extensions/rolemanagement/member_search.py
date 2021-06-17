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

import asyncio
from typing import AsyncIterator, Callable, List, Optional, Set

import discord


async def _member_yielder(
    members: Set[discord.Member],
) -> AsyncIterator[discord.Member]:

    # While the check function isn't expensive,
    # we can ensure this doesn't create issues
    # when applied to larger member lists
    # with periodic yielding of the event loop.

    for index, member in enumerate(members):
        if not index % 1000:
            await asyncio.sleep(0)
        yield member


async def search_filter(members: Set[discord.Member], query: dict) -> Set[discord.Member]:
    """
    Reusable filter
    """

    # sleep(0) use is used to yield control of the event loop for a cycle

    if query["everyone"]:
        return members

    if all_roles := query["all"]:
        members.intersection_update(*(role.members for role in all_roles))
        await asyncio.sleep(0)

    if none_roles := query["none"]:
        members.difference_update(*(role.members for role in none_roles))
        await asyncio.sleep(0)

    if any_roles := query["any"]:
        any_set: Set[discord.Member] = set()
        any_set.update(*(role.members for role in any_roles))
        members.intersection_update(any_set)
        await asyncio.sleep(0)

    if filter_obj := _non_set_filter(query):

        return {m async for m in _member_yielder(members) if filter_obj(m)}

    return members


def _non_set_filter(query: dict) -> Optional[Callable[[discord.Member], bool]]:
    """
    This could be unironically imporved by use of exec
    to create a more optimal function.

    However, these filter objects are not reused at all currently,
    and therefore isn't worth the cognitive overhead of
    consdiering the safety every time this is touched.

    As it stands, we collect the conditions as a
    list of lambdas then check that all apply, which is better than it previously was.

    Returns None if there are no applicable conditions in the query.
    """

    minimum_perms: Optional[discord.Permissions] = None
    if required_perms := query["hasperm"]:
        minimum_perms = discord.Permissions(**{x: True for x in required_perms})

    conditions: List[Callable[[discord.Member], bool]] = []

    if query["bots"]:
        conditions.append(lambda m: m.bot)
    elif query["humans"]:
        conditions.append(lambda m: not m.bot)

    if minimum_perms:
        conditions.append(lambda m: m.guild_permissions.is_superset(minimum_perms))

    if any_perm_list := query["anyperm"]:
        conditions.append(lambda m: any(value and perm in any_perm_list for perm, value in m.guild_permissions))

    if not_perm_list := query["notperm"]:
        conditions.append(lambda m: not any(value and perm in not_perm_list for perm, value in m.guild_permissions))

    if query["noroles"]:
        conditions.append(lambda m: not m._roles)

    if (exact_quantity := query["quantity"]) is not None:
        conditions.append(lambda m: len(m._roles) == exact_quantity)

    if (lt := query["lt"]) is not None:
        conditions.append(lambda m: len(m._roles) < lt)
    if (gt := query["gt"]) is not None:
        conditions.append(lambda m: len(m._roles) > gt)

    if above_role := query["above"]:
        conditions.append(lambda m: m.top_role > above_role)

    if below_role := query["below"]:
        conditions.append(lambda m: m.top_role < below_role)

    if not conditions:
        return None

    def actual_filter(m: discord.Member) -> bool:

        return all(func(m) for func in conditions)

    return actual_filter
