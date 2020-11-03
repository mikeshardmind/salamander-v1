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

import re

import apsw
import discord
from discord.ext import commands

from ...bot import Salamander, SalamanderContext
from ...checks import admin_or_perms
from ...utils import strip_variation_selectors

# discord might support more than this in an embed
IMG_RE = re.compile(r"\.(?:png|gif|jpg)$")


def is_image(a):
    return a.height and a.url and IMG_RE.match(a.url)


PRAGMAS = (
    "PRAGMA foreign_keys=ON ",
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = FULL",
)

BOARD_TABLE_CREATION = """
CREATE TABLE IF NOT EXISTS starboards (
    guild_id INTEGER NOT NULL,
    normalized_emoji TEXT NOT NULL,
    destination_channel_id INTEGER NOT NULL UNIQUE,
    required_reacts INTEGER NOT NULL CHECK( required_reacts > 0),
    PRIMARY KEY (guild_id, normalized_emoji)
);
"""

CHANNEL_SETTINGS_TABLE_CREATION = """
CREATE TABLE IF NOT EXISTS channel_settings (
    guild_id INTEGER NOT NULL REFERENCES starboards(guild_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    channel_id INTEGER NOT NULL PRIMARY KEY,
    allowed BOOLEAN DEFAULT false
);
"""

SOURCE_MESSAGE_TABLE_CREATION = """
CREATE TABLE IF NOT EXISTS source_messages (
    message_id INTEGER NOT NULL PRIMARY KEY,
    guild_id INTEGER NOT NULL REFERENCES starboards(guild_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    channel_id INTEGER NOT NULL,
    content TEXT NOT NULL
);
"""

REACTION_TABLE_CREATION = """
CREATE TABLE IF NOT EXISTS reactions (
    message_id INTEGER NOT NULL REFERENCES source_messages(message_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    normalized_emoji TEXT NOT NULL,
    FOREIGN KEY (guild_id, normalized_emoji) REFERENCES starboards(guild_id, normalized_emoji)
        ON UPDATE CASCADE ON DELETE CASCADE,
    PRIMARY KEY (message_id, user_id, normalized_emoji)
);
"""

GENERATED_MESSAGE_TABLE_CREATION = """
CREATE TABLE IF NOT EXISTS generated_messages (
    message_id INTEGER NOT NULL PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    normalized_emoji TEXT NOT NULL,
    source_message_id INTEGER NOT NULL REFERENCES source_messages(message_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (guild_id, normalized_emoji) REFERENCES starboards(guild_id, normalized_emoji)
        ON UPDATE CASCADE ON DELETE CASCADE
);
"""


class Starboard(commands.Cog):
    """
    Starboard commands
    """

    def __init__(self, bot: Salamander):
        self.bot: Salamander = bot
        self.conn: apsw.Connection = apsw.Connection("contrib_data/starboard.db")
        cursor = self.conn.cursor()
        for pragma in PRAGMAS:
            cursor.execute(pragma)
        for statement in (
            BOARD_TABLE_CREATION,
            CHANNEL_SETTINGS_TABLE_CREATION,
            SOURCE_MESSAGE_TABLE_CREATION,
            REACTION_TABLE_CREATION,
            GENERATED_MESSAGE_TABLE_CREATION,
        ):
            cursor.execute(statement)

    @commands.Cog.listener("on_raw_reaction_add")
    async def raw_react_add_handler(self, payload: discord.RawReactionActionEvent):

        if not payload.guild_id:
            return

        member = payload.member
        if not member:
            return

        if self.bot.member_is_considered_muted(member):
            return

        emoji = payload.emoji
        if emoji.is_custom_emoji():
            eid = str(emoji.id)
        else:
            eid = strip_variation_selectors(str(emoji))

        cursor = self.conn.cursor()

        row = cursor.execute(
            """
            SELECT destination_channel_id, required_reacts FROM starboards
            WHERE guild_id = ?1 AND normalized_emoji = ?2 AND EXISTS(
                SELECT 1 FROM channel_settings WHERE allowed and channel_id= ?3
            ) AND DATETIME(
                ((?4 >> 22) + 1420070400000) / 1000, 'unixepoch'
            ) > DATETIME('now', '-7 days')
            """,
            (payload.guild_id, eid, payload.channel_id, payload.message_id),
        ).fetchone()

        if not row:
            return

        destination_channel_id, _required_reacts = row

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return

        if not channel.permissions_for(guild.me).read_message_history:
            return

        try:
            msg = next(
                (m for m in self.bot.cached_messages if m.id == payload.message_id),
                None,
            ) or await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return

        if msg is None or msg.content is None or msg.author.id == member.id:
            return

        with self.conn:

            cursor.execute(
                """
                INSERT INTO source_messages (message_id, guild_id, channel_id, content)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (message_id) NOTHING
                """,
                (msg.id, guild.id, channel.id, msg.system_content),
            )

            cursor.execute(
                """
                INSERT INTO reactions (message_id, guild_id, user_id, normalized_emoji)
                VALUES (?,?,?,?)
                ON CONFLICT (message_id, user_id, normalized_emoji) DO NOTHING
                """,
                (msg.id, guild.id, member.id, eid),
            )

        row = cursor.execute(
            """
            SELECT COUNT(*) >= required_reacts AS is_above, content
            FROM reactions NATURAL JOIN starboards NATURAL JOIN source_messages
            WHERE normalized_emoji = ?1 AND guild_id = ?2 AND message_id =?3
            AND NOT EXISTS (
                SELECT 1 FROM generated_messages
                WHERE source_message_id =?3 AND normalized_emoji = ?1
            )
            """,
            (eid, payload.guild_id, msg.id),
        ).fetchone()

        if not row:
            return

        destination = guild.get_channel(destination_channel_id)
        if not destination:
            return

        if destination.permissions_for(guild.me).value & 18432 != 18432:
            return

        (content,) = row  # preserves content on edit

        author = msg.author

        try:
            color = author.color if author.color.value != 0 else None
        except AttributeError:  # happens if message author not in guild anymore.
            color = None

        if msg.embeds:
            # This should only be embeds generated from links
            em = msg.embeds[0]
            if content:

                description = "\n\n".join(filter(None, (content, em.description)))
                if len(description) > 2048:
                    description = f"{description[:2042]} [...]"

                em.description = description
                if not author.bot:
                    em.set_author(
                        name=author.display_name,
                        url=msg.jump_url,
                        icon_url=str(author.avatar_url),
                    )

        else:

            em = discord.Embed(timestamp=msg.created_at, color=color)
            em.description = msg.system_content
            em.set_author(
                name=author.display_name,
                url=msg.jump_url,
                icon_url=str(author.avatar_url),
            )

            # Mobile and OSX can actually send multiple in a single message,
            # we cant in a single embed
            # (not without abusing behavior made for twitter and webhook messages)
            if first_image := next((a for a in msg.attachments if is_image(a)), None):
                em.set_image(url=first_image.url)

        em.timestamp = msg.created_at
        em.add_field(
            name="Want to see this in context?",
            value=f"[Click to jump to original message]({msg.jump_url})",
            inline=False,
        )
        em.set_footer(text=f"{guild.name} | #{channel.name}")

        try:
            gen_message = await destination.send(embed=em)
        except discord.HTTPException:
            return

        cursor.execute(
            """
            INSERT INTO generated_messages(
                message_id, guild_id, channel_id, normalized_emoji, source_message_id
            )
            VALUES (?,?,?,?,?)
            """,
            (gen_message.id, guild.id, destination_channel_id, eid, msg.id),
        )
