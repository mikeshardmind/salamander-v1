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


def embed_from_member(member: discord.Member) -> discord.Embed:

    date_format_spec = "%B %d, %Y"
    em = discord.Embed(colour=member.color)

    if ln := len(member._roles):
        r_str = " ".join((r.mention for r in reversed(member.roles) if not r.is_default()))

        if len(r_str) > 1024:
            # This will break an embed field limit,
            # requires a substantial number of roles (over 30)
            # but just give up, this server is nonsensical
            em.add_field(
                name="User's roles not shown",
                value=f"Too many roles ({ln}) to display.",
                inline=False,
            )
        elif ln == 1:
            em.add_field(name="User's role", value=r_str, inline=False)
        else:
            em.add_field(name="User's roles", value=r_str, inline=False)

    join_str = member.joined_at.strftime(date_format_spec) if member.joined_at else "???"
    creation_str = member.created_at.strftime(date_format_spec)
    em.add_field(name="Created their account on", value=creation_str)
    em.add_field(name="Joined this server on", value=join_str)
    em.set_footer(text=f"Discord ID: {member.id}")
    a_name = f"{member} | {member.nick}" if member.nick else f"{member}"
    avatar = member.avatar_url_as(static_format="png")
    em.set_author(name=a_name, url=avatar)
    em.set_thumbnail(url=avatar)

    return em
