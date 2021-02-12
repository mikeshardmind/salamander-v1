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
import csv
import io
import logging
from typing import Dict, Iterator, List, Optional, Set, Union

import discord
from discord.ext import commands

from ...bot import Salamander, SalamanderContext, UserFeedbackError
from ...checks import admin_or_perms, mod_or_perms
from ...utils import (
    add_variation_selectors_to_emojis,
    resolve_as_roles,
    strip_variation_selectors,
)
from .converters import (
    ComplexActionConverter,
    ComplexSearchConverter,
    EmojiRolePairConverter,
    RoleSettingsConverter,
    RoleSyntaxConverter,
)
from .db_abstractions import (
    NoSuchRecord,
    ReactionRoleRecord,
    RoleSettings,
    get_member_sticky,
    update_member_sticky,
)

log = logging.getLogger("salamander.extensions.rolemanagement")


class RoleManagement(commands.Cog):
    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot

    async def all_are_valid_roles(
        self, ctx, *roles: discord.Role, detailed: bool = False
    ) -> bool:
        """
        Quick hierarchy check on a role set in syntax returned
        """
        author = ctx.author
        guild = ctx.guild

        # Author allowed

        if not guild.owner == author:
            auth_top = author.top_role
            if not (
                all(auth_top > role for role in roles)
                or await ctx.bot.is_owner(ctx.author)
            ):
                if detailed:
                    raise UserFeedbackError(
                        custom_message="You can't give away roles which are not below your top role."
                    )
                return False

        # Bot allowed

        if not guild.me.guild_permissions.manage_roles:
            if detailed:
                raise UserFeedbackError(custom_message="I can't manage roles.")
            return False

        if not guild.me == guild.owner:
            bot_top = guild.me.top_role
            if not all(bot_top > role for role in roles):
                if detailed:
                    raise UserFeedbackError(
                        custom_message="I can't give away roles which are not below my top role."
                    )
                return False

        # Sanity check on managed roles
        if any(role.managed for role in roles):
            if detailed:
                raise UserFeedbackError(
                    custom_message="Managed roles can't be assigned by this."
                )
            return False

        return True

    async def update_roles_atomically(
        self,
        *,
        who: discord.Member,
        give: List[discord.Role] = None,
        remove: List[discord.Role] = None,
    ):
        """
        Give and remove roles as a single op with some slight wrapping
        """
        me = who.guild.me
        give = give or []
        remove = remove or []
        hierarchy_testing = give + remove
        user_roles = who.roles
        roles = [r for r in user_roles if r not in remove]
        roles.extend([r for r in give if r not in roles])
        if sorted(roles) == user_roles:
            return
        if (
            any(r >= me.top_role for r in hierarchy_testing)
            or not me.guild_permissions.manage_roles
        ):
            raise UserFeedbackError(custom_message="Can't do that.")
        await who.edit(roles=roles)

    @mod_or_perms(manage_roles=True)
    @commands.guild_only()
    @commands.group(name="massrole", aliases=["mrole"])
    async def mrole(self, ctx: SalamanderContext):
        """
        Commands for mass role management
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    def search_filter(self, members: set, query: dict) -> set:
        """
        Reusable
        """

        if query["everyone"]:
            return members

        all_set: Set[discord.Member] = set()
        if query["all"]:
            first, *rest = query["all"]
            all_set = set(first.members)
            for other_role in rest:
                all_set &= set(other_role.members)

        none_set: Set[discord.Member] = set()
        if query["none"]:
            for role in query["none"]:
                none_set.update(role.members)

        any_set: Set[discord.Member] = set()
        if query["any"]:
            for role in query["any"]:
                any_set.update(role.members)

        minimum_perms: Optional[discord.Permissions] = None
        if query["hasperm"]:
            minimum_perms = discord.Permissions()
            minimum_perms.update(**{x: True for x in query["hasperm"]})

        def mfilter(m: discord.Member) -> bool:
            if query["bots"] and not m.bot:
                return False

            if query["humans"] and m.bot:
                return False

            if query["any"] and m not in any_set:
                return False

            if query["all"] and m not in all_set:
                return False

            if query["none"] and m in none_set:
                return False

            if query["hasperm"] and not m.guild_permissions.is_superset(minimum_perms):
                return False

            if query["anyperm"] and not any(
                bool(value and perm in query["anyperm"])
                for perm, value in iter(m.guild_permissions)
            ):
                return False

            if query["notperm"] and any(
                bool(value and perm in query["notperm"])
                for perm, value in iter(m.guild_permissions)
            ):
                return False

            if query["noroles"] and len(m.roles) != 1:
                return False

            # 0 is a valid option for these, everyone role not counted, ._roles doesnt include everyone
            if query["quantity"] is not None and len(m._roles) != query["quantity"]:
                return False

            if query["lt"] is not None and len(m._roles) >= query["lt"]:
                return False

            if query["gt"] is not None and len(m._roles) <= query["gt"]:
                return False

            top_role = m.top_role

            if query["above"] and top_role <= query["above"]:
                return False

            if query["below"] and top_role >= query["below"]:
                return False

            return True

        members = {m for m in members if mfilter(m)}

        return members

    @admin_or_perms(manage_roles=True)
    @commands.bot_has_guild_permissions(manage_roles=True)
    @mrole.command(name="user")
    async def mrole_user(
        self,
        ctx: SalamanderContext,
        users: commands.Greedy[discord.Member],
        *,
        _query: RoleSyntaxConverter,
    ) -> None:
        """
        adds/removes roles to one or more users

        You cannot add and remove the same role

        Example Usage:

        ```
        [p]massrole user Sinbad --add RoleToGive "Role with spaces to give"
        --remove RoleToRemove "some other role to remove" Somethirdrole
        ```

        ```
        [p]massrole user LoudMouthedUser ProfaneUser --add muted
        ```

        For role operations based on role membership, permissions had, or whether someone is a bot
        (or even just add to/remove from all) see `[p]massrole search` and `[p]massrole modify`
        """
        query = _query.parsed
        apply = query["add"] + query["remove"]
        if not await self.all_are_valid_roles(ctx, *apply, detailed=True):
            return

        for user in users:
            await self.update_roles_atomically(
                who=user, give=query["add"], remove=query["remove"]
            )

        await ctx.send("Done.")

    @mrole.command(name="search")
    async def mrole_search(
        self, ctx: SalamanderContext, *, _query: ComplexSearchConverter
    ):
        """
        Searches for users with the specified role criteria

        --has-all roles
        --has-none roles
        --has-any roles

        --has-no-roles
        --has-exactly-nroles number
        --has-more-than-nroles number
        --has-less-than-nroles number

        --has-perm permissions
        --any-perm permissions
        --not-perm permissions

        --above role
        --below role

        --only-humans
        --only-bots
        --everyone

        --csv

        csv output will be used if output would exceed embed limits, or if flag is provided
        """

        members = set(ctx.guild.members)
        query = _query.parsed
        members = self.search_filter(members, query)

        if len(members) < 50 and not query["csv"]:

            def chunker(memberset, size=3):
                ret_str = ""
                for i, m in enumerate(memberset, 1):
                    ret_str += m.mention
                    if i % size == 0:
                        ret_str += "\n"
                    else:
                        ret_str += " "
                return ret_str

            description = chunker(members)
            embed = discord.Embed(description=description)
            if ctx.guild:
                embed.color = ctx.guild.me.color
            await ctx.send(
                embed=embed, content=f"Search results for {ctx.author.mention}"
            )

        else:
            await self.send_maybe_chunked_csv(ctx, list(members))

    @staticmethod
    async def send_maybe_chunked_csv(ctx: SalamanderContext, members):
        chunk_size = 75000
        chunks = [
            members[i : (i + chunk_size)] for i in range(0, len(members), chunk_size)
        ]

        for part, chunk in enumerate(chunks, 1):

            csvf = io.StringIO()
            fieldnames = [
                "User ID",
                "Display Name",
                "Username#Discrim",
                "Joined Server",
                "Joined Discord",
            ]
            fmt = "%Y-%m-%d"
            writer = csv.DictWriter(csvf, fieldnames=fieldnames)
            writer.writeheader()
            for member in chunk:
                writer.writerow(
                    {
                        "User ID": member.id,
                        "Display Name": member.display_name,
                        "Username#Discrim": str(member),
                        "Joined Server": member.joined_at.strftime(fmt)
                        if member.joined_at
                        else None,
                        "Joined Discord": member.created_at.strftime(fmt),
                    }
                )

            csvf.seek(0)
            b_data = csvf.read().encode()
            data = io.BytesIO(b_data)
            data.seek(0)
            filename = f"{ctx.message.id}"
            if len(chunks) > 1:
                filename += f"-part{part}"
            filename += ".csv"
            await ctx.send(
                content=f"Data for {ctx.author.mention}",
                files=[discord.File(data, filename=filename)],
            )
            csvf.close()
            data.close()
            del csvf
            del data

    @mrole.command(name="modify")
    async def mrole_complex(
        self, ctx: SalamanderContext, *, _query: ComplexActionConverter
    ):
        """
        Similar syntax to search, while applying/removing roles

        --has-all roles
        --has-none roles
        --has-any roles

        --has-no-roles
        --has-exactly-nroles number
        --has-more-than-nroles number
        --has-less-than-nroles number

        --has-perm permissions
        --any-perm permissions
        --not-perm permissions

        --above role
        --below role

        --only-humans
        --only-bots
        --everyone

        --add roles
        --remove roles
        """
        query = _query.parsed
        apply = query["add"] + query["remove"]
        if not await self.all_are_valid_roles(ctx, *apply, detailed=True):
            return

        members = set(ctx.guild.members)
        members = self.search_filter(members, query)

        if len(members) > 100:
            await ctx.send(
                "This may take a while given the number of members to update."
            )

        async with ctx.typing():
            for member in members:
                if self.bot.member_is_considered_muted(member):
                    continue

                try:
                    await self.update_roles_atomically(
                        who=member, give=query["add"], remove=query["remove"]
                    )
                except UserFeedbackError:
                    log.debug(
                        "Internal filter failure on member id %d guild id %d query %s",
                        member.id,
                        ctx.guild.id,
                        query,
                    )
                except discord.HTTPException:
                    log.debug(
                        "Unpredicted failure for member id %d in guild id %d query %s",
                        member.id,
                        ctx.guild.id,
                        query,
                    )

        await ctx.send("Done.")

    def is_self_assign_eligible(
        self,
        who: discord.Member,
        role: discord.Role,
        role_settings: Optional[RoleSettings] = None,
    ) -> List[discord.Role]:
        """
        Returns a list of roles to be removed if this one is added, or raises an
        exception
        """

        guild = who.guild
        if role.managed:
            raise UserFeedbackError(
                custom_message="This role can't be assigned except by the associated integration."
            )
        if not guild.me.guild_permissions.manage_roles:
            raise UserFeedbackError(
                custom_message="I don't have permission to do that."
            )
        if role > guild.me.top_role and guild.me != guild.owner:
            raise UserFeedbackError(
                custom_message="I can't assign you that role (discord hierarchy applies here)"
            )

        role_details = role_settings or RoleSettings.from_databse(
            self.bot._conn, role.id, role.guild.id
        )
        self.check_required(who, role, role_details)
        return self.check_exclusivity(who, role, role_details)

    def check_required(
        self,
        who: discord.Member,
        role: discord.Role,
        role_settings: Optional[RoleSettings] = None,
    ) -> None:
        """
        Raises an error on missing reqs
        """

        role_details = role_settings or RoleSettings.from_databse(
            self.bot._conn, role.id, role.guild.id
        )

        if req_any := role_details.requires_any:
            for idx in req_any:
                if who._roles.has(idx):
                    break
            else:
                raise UserFeedbackError(
                    custom_message="You don't meet the requirements to self-assign this role."
                )

        if req_all := role_details.requires_all:
            for idx in req_all:
                if not who._roles.has(idx):
                    raise UserFeedbackError(
                        custom_message="You don't meet the requirements to self-assign this role."
                    )

        return None

    def check_exclusivity(
        self,
        who: discord.Member,
        role: discord.Role,
        role_settings: Optional[RoleSettings] = None,
    ) -> List[discord.Role]:
        """
        Returns a list of roles to remove, or raises an error
        """

        role_details = role_settings or RoleSettings.from_databse(
            self.bot._conn, role.id, role.guild.id
        )

        ex = role_details.exclusive_to
        conflicts = [r for r in who.roles if r.id in ex]

        for r in conflicts:
            if not RoleSettings.from_databse(
                self.bot._conn, r.id, role.guild.id
            ).self_removable:
                raise UserFeedbackError(
                    custom_message="You already have a role which conflicts with this one."
                )

        return conflicts

    async def maybe_update_guild(self, guild: discord.Guild):
        if not guild.unavailable and guild.large and not guild.chunked:
            await guild.chunk()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        DEP-WARN
        Section has been optimized assuming member._roles
        remains an iterable containing snowflakes
        """

        g = before.guild or after.guild

        if before._roles == after._roles:
            return

        lost, gained = set(before._roles), set(after._roles)
        lost, gained = lost - gained, gained - lost

        update_member_sticky(self.bot._conn, g.id, before.id, gained, lost)

    @commands.Cog.listener("on_member_update")
    async def member_verification_hatch(
        self, before: discord.Member, after: discord.Member
    ):

        if before.pending and not after.pending:
            await self.on_member_join(after)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):

        if member.pending:
            return

        guild = member.guild
        if not guild.me.guild_permissions.manage_roles:
            return

        if self.bot.member_is_considered_muted(member):
            return

        to_add = []

        for rid in get_member_sticky(self.bot._conn, guild.id, member.id):
            role = guild.get_role(rid)
            if role and not role.managed and role < guild.me.top_role:
                to_add.append(role)

        await member.add_roles(*to_add)

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.raw_models.RawReactionActionEvent
    ):

        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild:
            await self.maybe_update_guild(guild)
        else:
            return

        member = guild.get_member(payload.user_id)

        if member is None or member.bot:
            return

        if self.bot.member_is_considered_muted(member):
            return

        try:
            rr = ReactionRoleRecord.from_raw_reaction(self.bot._conn, payload)
            rid = rr.role_id
            role_settings = RoleSettings.from_databse(
                self.bot._conn, rid, payload.guild_id
            )
        except NoSuchRecord:
            return

        if not role_settings.self_assignable:
            return

        role = guild.get_role(rid)
        if role is None or member._roles.has(rid):
            return

        try:
            remove = self.is_self_assign_eligible(member, role)
        except UserFeedbackError:
            pass
        else:
            await self.update_roles_atomically(who=member, give=[role], remove=remove)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(
        self, payload: discord.raw_models.RawReactionActionEvent
    ):

        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild:
            await self.maybe_update_guild(guild)
        else:
            return

        member = guild.get_member(payload.user_id)

        if member is None or member.bot:
            return

        if self.bot.member_is_considered_muted(member):
            return

        try:
            rr = ReactionRoleRecord.from_raw_reaction(self.bot._conn, payload)
            rid = rr.role_id
            role_settings = RoleSettings.from_databse(
                self.bot._conn, rid, payload.guild_id
            )
        except NoSuchRecord:
            return

        if not rr.react_remove_triggers_removal:
            return

        if not role_settings.self_removable:
            return

        role = guild.get_role(rid)

        if not role or not member._roles.has(rid):
            return

        if guild.me.guild_permissions.manage_roles and guild.me.top_role > role:
            await self.update_roles_atomically(who=member, give=None, remove=[role])

    async def cog_before_invoke(self, ctx):
        if ctx.guild:
            await self.maybe_update_guild(ctx.guild)

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @commands.command(name="hackrole", ignore_extra=False)
    async def hackrole(self, ctx: SalamanderContext, user_id: int, role: str):
        """
        Puts a stickyrole on someone not in the server.
        """

        roles = resolve_as_roles(ctx.guild, role)
        if not roles:
            raise UserFeedbackError(custom_message="That wasn't a role.")

        elif len(roles) > 1:
            raise UserFeedbackError(
                custom_message="There appears to be more than one role with that name, "
                "for safety, I won't act on this (use the role ID)"
            )

        actual_role = roles[0]

        if not await self.all_are_valid_roles(ctx, actual_role, detailed=True):
            return

        rid = actual_role.id

        role_settings = RoleSettings.from_databse(self.bot._conn, rid, ctx.guild.id)
        if not role_settings.sticky:
            raise UserFeedbackError(custom_message="This only works on sticky roles.")

        member = ctx.guild.get_member(user_id)

        if member:
            raise UserFeedbackError(
                custom_message="They are in the server, use the normal means."
            )

        update_member_sticky(self.bot._conn, ctx.guild.id, user_id, (rid,), ())
        await ctx.send("Done.")

    # @commands.is_owner()
    # @commands.command(name="rrcleanup", hidden=True)
    # async def rolemanagementcleanup(self, ctx: SalamanderContext):
    # TODO

    # @commands.cooldown(1, 7200, commands.BucketType.guild)
    # @admin_or_perms(manage_guild=True)
    # @commands.guild_only()
    # @commands.command()
    # async def rolebindservercleanup(self, ctx: SalamanderContext):
    #     """
    #     Cleanup binds that don't exist anymore.
    #     """
    #
    # TODO

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @commands.command(name="clearmessagebinds")
    async def clear_message_binds(
        self, ctx: commands.Context, channel: discord.TextChannel, message_id: int
    ):
        """
        Clear all binds from a message.
        """
        try:
            await channel.fetch_message(message_id)
        except discord.HTTPException:
            raise UserFeedbackError(custom_message="No such message")

        ReactionRoleRecord.remove_all_on_message(self.bot._conn, message_id)
        await ctx.send("Done.")

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.command(name="bulkrolebind")
    async def bulk_role_bind_command(
        self,
        ctx: SalamanderContext,
        channel: discord.TextChannel,
        message_id: int,
        *,
        emoji_role_pairs: EmojiRolePairConverter,
    ):
        """
        Add role binds to a message.

        Emoji role pairs should be any number of pairs
        of emoji and roles seperated by spaces.
        Role can be specified by ID or name.
        If using a name which includes spaces, enclose in quotes.

        Example usage:

        ```
        [p]bulkrolebind
        \N{DIGIT ONE}\N{VARIATION SELECTOR-16}\N{COMBINING ENCLOSING KEYCAP}
        "Role One"
        \N{DIGIT TWO}\N{VARIATION SELECTOR-16}\N{COMBINING ENCLOSING KEYCAP}
        Role-two
        ```
        """

        pairs = emoji_role_pairs.pairs

        if not await self.all_are_valid_roles(ctx, *pairs.values(), detailed=True):
            return

        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return await ctx.send("No such message")

        to_store: Dict[str, discord.Role] = {}
        _emoji: Optional[Union[discord.Emoji, str]]

        for emoji, role in pairs.items():

            _emoji = discord.utils.find(lambda e: str(e) == emoji, self.bot.emojis)
            if _emoji is None:
                try:
                    await ctx.message.add_reaction(
                        add_variation_selectors_to_emojis(emoji)
                    )
                except discord.HTTPException:
                    raise UserFeedbackError(custom_message=f"No such emoji {emoji}")
                else:
                    _emoji = emoji
                    eid = strip_variation_selectors(emoji)
            else:
                eid = str(_emoji.id)

            if not any(str(r) == emoji for r in message.reactions):
                try:
                    await message.add_reaction(_emoji)
                except discord.HTTPException:
                    raise UserFeedbackError(
                        custom_message="Hmm, that message couldn't be reacted to"
                    )

            to_store[eid] = role

        for eid, role in to_store.items():
            ReactionRoleRecord(
                ctx.guild.id, message.channel.id, message.id, eid, role.id, True
            ).to_database(self.bot._conn)

        await ctx.send(
            f"Remember, the reactions only function according to "
            f"the rules set for the roles using `{ctx.prefix}roleset`",
            delete_after=30,
        )

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @commands.command(name="rolebind")
    async def bind_role_to_reactions(
        self,
        ctx: SalamanderContext,
        role: discord.Role,
        channel: discord.TextChannel,
        msgid: int,
        emoji: str,
    ):
        """
        Binds a role to a reaction on a message.

        The role is only given if the criteria for it are met.
        Make sure you configure the other settings for a role using `[p]roleset`
        """

        if not await self.all_are_valid_roles(ctx, role, detailed=True):
            return

        try:
            message = await channel.fetch_message(msgid)
        except discord.HTTPException:
            raise UserFeedbackError(custom_message="No such message")

        _emoji: Optional[Union[discord.Emoji, str]]

        _emoji = discord.utils.find(lambda e: str(e) == emoji, self.bot.emojis)
        if _emoji is None:
            try:
                await ctx.message.add_reaction(emoji)
            except discord.HTTPException:
                raise UserFeedbackError(custom_message="No such emoji")
            else:
                _emoji = emoji
                eid = strip_variation_selectors(emoji)
        else:
            eid = str(_emoji.id)

        if not any(str(r) == emoji for r in message.reactions):
            try:
                await message.add_reaction(_emoji)
            except discord.HTTPException:
                raise UserFeedbackError(
                    custom_message="Hmm, that message couldn't be reacted to"
                )

        ReactionRoleRecord(
            ctx.guild.id, message.channel.id, message.id, eid, role.id, True
        ).to_database(self.bot._conn)

        role_settings = RoleSettings.from_databse(self.bot._conn, role.id, ctx.guild.id)

        self_assign, self_remove = (
            role_settings.self_assignable,
            role_settings.self_removable,
        )

        if self_assign and self_remove:
            await ctx.send(
                f"Role bound. "
                f"This role is both self assignable and self removable already. "
                f"If you need to modify this or any requirements related to this role, "
                f"remember to use `{ctx.prefix}roleset`."
            )
            return

        if self_assign:

            await ctx.send(
                "This role is self assignable, "
                "but not self removable. "
                "Would you like to make it self removable? "
                "(Options are yes or no)"
            )
            try:
                m = await ctx.bot.wait_for(
                    "message",
                    check=lambda m: m.channel.id == ctx.channel.id
                    and m.author.id == ctx.author.id,
                    timeout=30,
                )
            except asyncio.TimeoutError:
                await ctx.send(
                    f"I won't change this for you without "
                    f"confirmation of it not being intentional. "
                    f"If you decide to change this later, use `{ctx.prefix}roleset`."
                )
            else:
                if (resp := m.content.casefold()) == "yes":
                    role_settings.set_self_removable(self.bot._conn, True)
                    await ctx.send("Ok, I've made the role self removable")
                elif resp == "no":
                    await ctx.send("Got it, leaving it alone.")

        elif self_remove:
            await ctx.send(
                "This role is self removable, but nor self assignable. "
                "While this is sometimes intentional, "
                "this particular configuration is usually a mistake. "
                "Would you like to make this role self assignable to go with that? "
                "(Options are yes or no)"
            )
            try:
                m = await ctx.bot.wait_for(
                    "message",
                    check=lambda m: m.channel.id == ctx.channel.id
                    and m.author.id == ctx.author.id,
                    timeout=30,
                )
            except asyncio.TimeoutError:
                await ctx.send(
                    f"I won't change this for you without "
                    f"confirmation of it not being intentional. "
                    f"If you decide to change this later, use `{ctx.prefix}roleset`."
                )

            else:
                if (resp := m.content.casefold()) == "yes":
                    role_settings.set_self_assignable(self.bot._conn, True)
                    await ctx.send("Ok, I've made the role self assignable")
                elif resp == "no":
                    await ctx.send("Got it, change was intentional.")
                else:
                    await ctx.send(
                        f"That did not appear to be a yes or a no. "
                        f"If you need to change this, use `{ctx.prefix}roleset`"
                    )

        else:

            await ctx.send(
                "This role is neither self assignable not self removable. "
                "This rolebind will be essentiall useless without changing that. "
                "Would you like me to make it self assignable? (Options are yes or no)"
            )

            try:
                m = await ctx.bot.wait_for(
                    "message",
                    check=lambda m: m.channel.id == ctx.channel.id
                    and m.author.id == ctx.author.id,
                    timeout=30,
                )
            except asyncio.TimeoutError:
                await ctx.send(
                    f"I won't wait forever for a response. "
                    f"If you decide to change this later, use `{ctx.prefix}roleset`."
                )
                return
            else:
                if (resp := m.content.casefold()) == "yes":
                    role_settings.set_self_assignable(self.bot._conn, True)
                    await ctx.send(
                        "Would you also like it to be self removable? (Options are yes or no)"
                    )
                    try:
                        m2 = await ctx.bot.wait_for(
                            "message",
                            check=lambda m: m.channel.id == ctx.channel.id
                            and m.author.id == ctx.author.id,
                            timeout=30,
                        )
                    except asyncio.TimeoutError:
                        await ctx.send(
                            f"I won't wait forever for a response. "
                            f"If you decide to change this later, use `{ctx.prefix}roleset`."
                        )
                        return
                    else:
                        if (resp2 := m2.content.casefold()) == "yes":
                            role_settings.set_self_removable(self.bot._conn, True)
                            await ctx.send(
                                "Ok, I've made the role self removable as well."
                            )
                        elif resp2 == "no":
                            await ctx.send("Got it, leaving it alone.")
                        else:
                            return await ctx.send(
                                f"That did not appear to be a yes or a no. "
                                f"If you need to change this, use `{ctx.prefix}roleset`"
                            )

                elif resp == "no":
                    return await ctx.send(
                        "Ok, I assume you know what you are doing then."
                    )
                else:
                    return await ctx.send(
                        f"That did not appear to be a yes or a no. "
                        f"If you need to change this, use `{ctx.prefix}roleset`"
                    )

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @commands.command(name="roleunbind")
    async def unbind_role_from_reactions(
        self, ctx: commands.Context, role: discord.Role, msgid: int, emoji: str
    ):
        """
        Unbinds a role from a reaction on a message.
        """

        if not await self.all_are_valid_roles(ctx, role, detailed=True):
            return

        ReactionRoleRecord.remove_entry(
            self.bot._conn, msgid, strip_variation_selectors(emoji)
        )
        await ctx.send("Done.")

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @commands.group(name="roleset")
    async def rgroup(self, ctx: SalamanderContext):
        """
        Settings for role requirements.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @rgroup.command(name="bulkset")
    async def r_bulkset(
        self,
        ctx: SalamanderContext,
        roles: commands.Greedy[discord.Role],
        *,
        settings: RoleSettingsConverter,
    ):
        """
        Bulk settings for a list of roles.
        Any settings not provided will be left alone.

        --(no-)selfadd
        --(no-)selfrem
        --(no-)sticky
        """

        if not roles:
            return await ctx.send_help()

        if not await self.all_are_valid_roles(ctx, *roles, detailed=True):
            return

        if all(x is None for x in settings):
            raise commands.BadArgument("Must provide at least one setting.")

        to_merge = settings.as_mergeable()
        RoleSettings.bulk_update_bools(
            self.bot._conn, ctx.guild.id, *{r.id for r in roles}, **to_merge
        )
        await ctx.send("Settings for the specified roles have been modified.")

    @commands.guild_only()
    @rgroup.command(name="viewreactions")
    async def rg_view_reactions(self, ctx: SalamanderContext):
        """
        View the reactions enabled for the server.
        """
        all_records = (
            "\n".join(self.build_messages_for_react_role(ctx.guild, use_embeds=False))
            or "No bound react roles."
        )
        await ctx.send_paged(all_records)

    @rgroup.command(name="viewrole", ignore_extra=False)
    async def rg_view_role(self, ctx: SalamanderContext, role: str):
        """
        Views the current settings for a role.
        """

        roles = resolve_as_roles(ctx.guild, role)
        if not roles:
            raise UserFeedbackError(custom_message="That wasn't a role.")

        elif len(roles) > 1:
            raise UserFeedbackError(
                custom_message="There appears to be more than one role with that name, "
                "for safety, I won't act on this (use the role ID)"
            )

        rid = roles[0].id

        try:
            rsets = RoleSettings.from_databse(self.bot._conn, rid, ctx.guild.id)
        except NoSuchRecord:
            return await ctx.send(
                "This role has not been setup (no settings applied to it)"
            )

        output = (
            f"This role:\n{'is' if rsets.self_assignable else 'is not'} self assignable"
            f"\n{'is' if rsets.self_removable else 'is not'} self removable"
            f"\n{'is' if rsets.sticky else 'is not'} sticky."
        )
        if r_any := rsets.requires_any:
            rstring = ", ".join(r.name for r in ctx.guild.roles if r.id in r_any)
            output += f"\nThis role requires any of the following roles: {rstring}"
        if r_all := rsets.requires_all:
            rstring = ", ".join(r.name for r in ctx.guild.roles if r.id in r_all)
            output += f"\nThis role requires all of the following roles: {rstring}"
        if r_exto := rsets.exclusive_to:
            rstring = ", ".join(r.name for r in ctx.guild.roles if r.id in r_exto)
            output += (
                f"\nThis role is mutually exclusive to the following roles: {rstring}"
            )

        await ctx.send_paged(output)

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @rgroup.command(name="exclusive")
    async def set_exclusivity(self, ctx: SalamanderContext, *roles: discord.Role):
        """
        Takes 2 or more roles and sets them as exclusive to eachother.
        """

        _roles = {r.id for r in roles}

        if not await self.all_are_valid_roles(ctx, *roles, detailed=True):
            return

        if len(_roles) < 2:
            raise UserFeedbackError(
                custom_message="You need to provide at least 2 roles"
            )

        RoleSettings.bulk_add_exclusivity(self.bot._conn, ctx.guild.id, _roles)
        await ctx.send("Done.")

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @rgroup.command(name="unexclusive")
    async def unset_exclusivity(self, ctx: SalamanderContext, *roles: discord.Role):
        """
        Takes any number of roles and removes their exclusivity settings.
        """

        _roles = {r.id for r in roles}

        if not await self.all_are_valid_roles(ctx, *roles, detailed=True):
            return

        if len(_roles) < 2:
            raise UserFeedbackError(
                custom_message="You need to provide at least 2 roles"
            )

        RoleSettings.bulk_remove_exclusivity(self.bot._conn, ctx.guild.id, _roles)
        await ctx.send("Done.")

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @rgroup.command(name="sticky")
    async def setsticky(
        self, ctx: SalamanderContext, role: discord.Role, yes_or_no: bool
    ):
        """
        Sets whether a role should be reapplied to people who leave and rejoin.
        """
        if not await self.all_are_valid_roles(ctx, role, detailed=True):
            return
        RoleSettings.bulk_update_bools(
            self.bot._conn, ctx.guild.id, role.id, sticky=yes_or_no
        )
        await ctx.send("Done.")

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @rgroup.command(name="selfrem")
    async def selfrem(
        self, ctx: SalamanderContext, role: discord.Role, yes_or_no: bool
    ):
        """
        Sets if a role is self-removable.
        """
        if not await self.all_are_valid_roles(ctx, role, detailed=True):
            return
        RoleSettings.bulk_update_bools(
            self.bot._conn, ctx.guild.id, role.id, self_removable=yes_or_no
        )
        await ctx.send("Done.")

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @rgroup.command(name="selfadd")
    async def selfadd(
        self, ctx: SalamanderContext, role: discord.Role, yes_or_no: bool
    ):
        """
        Sets if a role is self-assignable.
        """
        if not await self.all_are_valid_roles(ctx, role, detailed=True):
            return
        RoleSettings.bulk_update_bools(
            self.bot._conn, ctx.guild.id, role.id, self_assignable=yes_or_no
        )
        await ctx.send("Done.")

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @rgroup.command(name="requireall")
    async def reqall(
        self, ctx: SalamanderContext, role: discord.Role, *roles: discord.Role
    ):
        """
        Sets the required roles to gain a role.

        Takes a role plus zero or more other roles.
        The additional roles are treated as the requirements of the first.
        """
        rs = {r.id for r in roles if r != role}
        RoleSettings.set_req_all(self.bot._conn, ctx.guild.id, role.id, *rs)
        await ctx.send("Done.")

    @commands.bot_has_guild_permissions(manage_roles=True)
    @admin_or_perms(manage_guild=True, manage_roles=True)
    @commands.guild_only()
    @rgroup.command(name="requireany")
    async def reqany(
        self, ctx: SalamanderContext, role: discord.Role, *roles: discord.Role
    ):
        """
        Sets a role to require already having one of another.

        Takes a role plus zero or more other roles.
        The additional roles are treated as the requirements of the first.
        """
        rs = {r.id for r in roles if r != role}
        RoleSettings.set_req_any(self.bot._conn, ctx.guild.id, role.id, *rs)
        await ctx.send("Done.")

    @commands.guild_only()
    @commands.group(name="srole")
    async def srole(self, ctx: SalamanderContext):
        """
        Self assignable role commands.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @commands.guild_only()
    @srole.command(name="list")
    async def srole_list(self, ctx: SalamanderContext):
        """
        Lists the selfroles.
        """
        rids = RoleSettings.self_assignable_ids_in_guild(self.bot._conn, ctx.guild.id)
        output = "\n".join((r.name for r in ctx.guild.roles if r.id in rids))
        await ctx.send_paged(output, box=True, prepend="Self-Assignable Roles")

    @commands.guild_only()
    @srole.command(name="add", ignore_extra=False)
    async def sadd(self, ctx: SalamanderContext, role: str):
        """
        Join a role.
        """

        if self.bot.member_is_considered_muted(ctx.author):
            return

        roles = resolve_as_roles(ctx.guild, role)
        if not roles:
            raise UserFeedbackError(custom_message="That wasn't a role.")

        elif len(roles) > 1:
            raise UserFeedbackError(
                custom_message="There appears to be more than one role with that name, "
                "for safety, I won't act on this (use the role ID)"
            )

        actual_role = roles[0]

        role_settings = RoleSettings.from_databse(
            self.bot._conn, actual_role.id, ctx.guild.id
        )

        if not role_settings.self_assignable:
            raise UserFeedbackError(custom_message="That isn't a self-assignable role.")

        remove = self.is_self_assign_eligible(ctx.author, actual_role, role_settings)

        await self.update_roles_atomically(
            who=ctx.author, give=[actual_role], remove=remove
        )
        await ctx.send("Done.")

    @commands.guild_only()
    @srole.command(name="remove", ignore_extra=False)
    async def srem(self, ctx: SalamanderContext, role: str):
        """
        Leave a role.
        """
        if self.bot.member_is_considered_muted(ctx.author):
            return

        roles = resolve_as_roles(ctx.guild, role)
        if not roles:
            raise UserFeedbackError(custom_message="That wasn't a role.")

        elif len(roles) > 1:
            raise UserFeedbackError(
                custom_message="There appears to be more than one role with that name, "
                "for safety, I won't act on this (use the role ID)"
            )

        actual_role = roles[0]
        rid = actual_role.id

        if RoleSettings.from_databse(self.bot._conn, rid, ctx.guild.id).self_removable:
            await self.update_roles_atomically(who=ctx.author, remove=[actual_role])
            await ctx.send("Done.")
        else:
            raise UserFeedbackError(
                custom_message=f"You aren't allowed to remove `{actual_role}` from yourself {ctx.author.mention}!`"
            )

    def build_messages_for_react_role(
        self, guild: discord.Guild, use_embeds=True
    ) -> Iterator[str]:
        """
        Builds info.

        Info is suitable for passing to embeds if use_embeds is True
        """

        associated_react_roles = ReactionRoleRecord.all_in_guild(
            self.bot._conn, guild.id
        )

        linkfmt = (
            "[message #{message_id}](https://discordapp.com/channels/{guild_id}/{channel_id}/{message_id})"
            if use_embeds
            else "<https://discordapp.com/channels/{guild_id}/{channel_id}/{message_id}>"
        )

        for record in associated_react_roles:

            role = guild.get_role(record.role_id)
            if not role:
                continue

            link = linkfmt.format(
                guild_id=record.guild_id,
                channel_id=record.channel_id,
                message_id=record.message_id,
            )

            emoji_info = record.reaction_string
            emoji: Union[discord.Emoji, str]
            if emoji_info.isdigit():
                emoji = (
                    discord.utils.get(self.bot.emojis, id=int(emoji_info))
                    or f"A custom enoji with id {emoji_info}"
                )
            else:
                emoji = add_variation_selectors_to_emojis(emoji_info)

            yield f"{role.name} is bound to {emoji} on {link}"

    # Below is just a common extra handler for this specific case

    @rg_view_role.error
    @hackrole.error
    @sadd.error
    @srem.error
    async def ignore_extra_hanlder(self, ctx, exc):
        if isinstance(exc, commands.TooManyArguments):
            await ctx.send(
                "You've given me what appears to be more than 1 role. "
                "If your role name has spaces in it, quote it."
            )
