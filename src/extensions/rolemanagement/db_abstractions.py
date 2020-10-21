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

import contextlib
import itertools
from typing import Iterable, List, NamedTuple, Sequence

import apsw
import discord

from ...utils import strip_variation_selectors

# A lot of the below won't be further optimized until it's definitively needed.
# This is kept relatively simple, but it is definitely possible that this can be made more optimal.


class NoSuchRecord(Exception):
    pass


def get_member_sticky(
    conn: apsw.Connection, guild_id: int, member_id: int,
) -> Sequence[int]:

    cursor = conn.cursor()

    return tuple(
        row[0]
        for row in cursor.execute(
            """
        SELECT role_id FROM roles_stuck_to_members
        WHERE user_id = ? AND guild_id = ?
        """,
            (member_id, guild_id),
        )
    )


def update_member_sticky(
    conn: apsw.Connection,
    guild_id: int,
    member_id: int,
    added_roles: Iterable[int],
    removed_roles: Iterable[int],
):
    with contextlib.closing(conn.cursor()) as cursor, conn:

        cursor.execute(
            """
            INSERT INTO guild_settings (guild_id) VALUES (?)
            ON CONFLICT (guild_id) DO NOTHING
            """,
            (guild_id,),
        )
        cursor.execute(
            """
            INSERT INTO user_settings(user_id) VALUES (?)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (member_id,),
        )
        cursor.execute(
            """
            INSERT INTO member_settings (user_id, guild_id) VALUES (?,?)
            ON CONFLICT (user_id, guild_id) DO NOTHING
            """,
            (member_id, guild_id),
        )
        if removed_roles:
            cursor.executemany(
                """
                DELETE FROM roles_stuck_to_members WHERE
                guild_id = ? AND user_id = ? AND role_id = ?
                """,
                tuple((guild_id, member_id, rid) for rid in removed_roles),
            )
        if added_roles:
            cursor.executemany(
                """
                INSERT INTO roles_stuck_to_members (guild_id, user_id, role_id)
                SELECT ?1, ?2, ?3
                WHERE EXISTS(SELECT 1 FROM role_settings WHERE role_id = ?3 AND sticky)
                ON CONFLICT (guild_id, user_id, role_id) DO NOTHING
                """,
                tuple((guild_id, member_id, rid) for rid in added_roles),
            )


class ReactionRoleRecord(NamedTuple):
    guild_id: int
    channel_id: int
    message_id: int
    reaction_string: str
    role_id: int
    react_remove_triggers_removal: bool

    @classmethod
    def all_in_guild(cls, conn: apsw.Connection, guild_id: int):
        cursor = conn.cursor()
        rows = cursor.execute(
            """
            SELECT guild_id, channel_id, message_id, reaction_string, role_id, react_remove_triggers_removal
            FROM react_role_entries
            WHERE guild_id=?
            """,
            (guild_id,),
        )

        return [cls(*row) for row in rows]

    @staticmethod
    def remove_entry(conn: apsw.Connection, message_id: int, reaction_str: str):
        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.execute(
                """
                DELETE FROM react_role_entries WHERE message_id = ? AND reaction_string = ?
                """,
                (message_id, strip_variation_selectors(reaction_str)),
            )

    @staticmethod
    def remove_all_on_message(conn: apsw.Connection, message_id: int):
        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.execute(
                """
                DELETE FROM react_role_entries WHERE message_id = ?
                """,
                (message_id,),
            )

    @classmethod
    def from_raw_reaction(
        cls, conn: apsw.Connection, payload: discord.RawReactionActionEvent
    ):
        emoji = payload.emoji
        if emoji.is_custom_emoji():
            eid = str(emoji.id)
        else:
            eid = strip_variation_selectors(str(emoji))

        return cls.from_database(conn, payload.message_id, eid)

    def to_database(self, conn: apsw.Connection):

        to_insert = (
            self.guild_id,
            self.channel_id,
            self.message_id,
            strip_variation_selectors(self.reaction_string),  # just in case
            self.role_id,
            self.react_remove_triggers_removal,
        )

        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (self.guild_id,),
            )
            cursor.execute(
                """
                INSERT INTO role_settings (role_id, guild_id) VALUES (?,?)
                ON CONFLICT (role_id) DO NOTHING
                """,
                (self.role_id, self.guild_id),
            )
            cursor.execute(
                """
                INSERT INTO react_role_entries (guild_id, channel_id, message_id, reaction_string, role_id, react_remove_triggers_removal)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT (message_id, reaction_string)
                DO UPDATE SET
                    role_id=excluded.role_id,
                    react_remove_triggers_removal=excluded.react_remove_triggers_removal
                """,
                to_insert,
            )

    @classmethod
    def from_database(cls, conn: apsw.Connection, message_id: int, reaction_str: str):

        cursor = conn.cursor()

        row = cursor.execute(
            """
            SELECT guild_id, channel_id, message_id, reaction_string, role_id, react_remove_triggers_removal
            FROM react_role_entries
            WHERE message_id = ? AND reaction_string = ?
            """,
            (message_id, reaction_str),
        ).fetchone()

        if not row:
            raise NoSuchRecord()

        return cls(*row)


class RoleSettings(NamedTuple):
    role_id: int
    guild_id: int
    self_assignable: bool
    self_removable: bool
    sticky: bool
    exclusive_to: Sequence[int]
    requires_any: Sequence[int]
    requires_all: Sequence[int]

    @staticmethod
    def self_assignable_ids_in_guild(conn: apsw.Connection, guild_id: int) -> List[int]:
        cursor = conn.cursor()

        return [
            r[0]
            for r in cursor.execute(
                """
                SELECT role_id FROM role_settings
                WHERE guild_id = ? AND self_assignable
                """,
                (guild_id,),
            )
        ]

    @staticmethod
    def bulk_remove_exclusivity(
        conn: apsw.Connection, guild_id: int, role_ids: Iterable[int]
    ):

        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.executemany(
                """
                DELETE FROM role_mutual_exclusivity
                WHERE role_id_1 = ?1 OR role_id_2 = ?1
                """,
                tuple((rid,) for rid in set(role_ids)),
            )

    @staticmethod
    def bulk_add_exclusivity(
        conn: apsw.Connection, guild_id: int, role_ids: Iterable[int]
    ):

        ids = list(set(role_ids))
        ids.sort()

        ordered_pairs = tuple(itertools.combinations(ids, 2))

        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (guild_id,),
            )
            cursor.executemany(
                """
                INSERT INTO role_settings (role_id, guild_id) VALUES (?,?)
                ON CONFLICT (role_id) DO NOTHING
                """,
                tuple((rid, guild_id) for rid in ids),
            )
            cursor.executemany(
                """
                DELETE FROM role_mutual_exclusivity
                WHERE role_id_1 = ?1 OR role_id_2 = ?1
                """,
                tuple((rid,) for rid in ids),
            )
            cursor.executemany(
                """
                INSERT INTO role_mutual_exclusivity (role_id_1, role_id_2) VALUES (?,?)
                ON CONFLICT (role_id_1, role_id_2) DO NOTHING
                """,
                ordered_pairs,
            )

    @staticmethod
    def bulk_update_bools(
        conn: apsw.Connection, guild_id: int, *role_ids: int, **kwargs: bool
    ):

        for k in kwargs:
            if k not in ("self_assignable", "self_removable", "sticky"):
                raise RuntimeError(
                    f"WTF happened here, abort, bad unsafe query construction, bad key: {k}"
                )

        if not kwargs:
            return

        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (guild_id,),
            )
            safe_keys = ", ".join(kwargs.keys())
            safe_val_binds = ", ".join(f":{k}" for k in kwargs.keys())
            safe_update_set = ", ".join(f"{k}=excluded.{k}" for k in kwargs.keys())

            cursor.executemany(
                f"""
                INSERT INTO role_settings (role_id, guild_id, {safe_keys})
                VALUES (:role_id, :guild_id, {safe_val_binds})
                ON CONFLICT (role_id)
                DO UPDATE SET {safe_update_set}
                """,
                tuple(
                    {"role_id": role_id, "guild_id": guild_id, **kwargs}
                    for role_id in role_ids
                ),
            )

    def set_self_removable(self, conn: apsw.Connection, val: bool):
        cursor = conn.cursor()
        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (self.guild_id,),
            )
            cursor.execute(
                """
                INSERT INTO role_settings (role_id, guild_id, self_removable) VALUES (?,?,?)
                ON CONFLICT (role_id)
                DO UPDATE SET
                    self_removable=excluded.self_removable
                """,
                (self.role_id, self.guild_id, val),
            )

    def set_self_assignable(self, conn: apsw.Connection, val: bool):
        cursor = conn.cursor()
        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (self.guild_id,),
            )
            cursor.execute(
                """
                INSERT INTO role_settings (role_id, guild_id, self_assignable) VALUES (?,?,?)
                ON CONFLICT (role_id)
                DO UPDATE SET
                    self_assignable=excluded.self_assignable
                """,
                (self.role_id, self.guild_id, val),
            )

    def set_sticky(self, conn: apsw.Connection, val: bool):
        cursor = conn.cursor()
        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (self.guild_id,),
            )
            cursor.execute(
                """
                INSERT INTO role_settings (role_id, guild_id, sticky) VALUES (?,?,?)
                ON CONFLICT (role_id)
                DO UPDATE SET
                    sticky=excluded.sticky
                """,
                (self.role_id, self.guild_id, val),
            )

    @staticmethod
    def set_req_any(
        conn: apsw.Connection, guild_id: int, role_id: int, *req_role_ids: int
    ):
        total_role_ids = {
            role_id,
            *req_role_ids,
        }
        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (guild_id,),
            )
            cursor.executemany(
                """
                INSERT INTO role_settings (role_id, guild_id) VALUES (?,?)
                ON CONFLICT (role_id) DO NOTHING
                """,
                tuple((rid, guild_id) for rid in total_role_ids),
            )
            cursor.execute(
                """
                DELETE FROM role_requires_any WHERE role_id = ?
                """,
                (role_id,),
            )
            cursor.executemany(
                """
                INSERT INTO role_requires_any (role_id, required_role_id) VALUES (?,?)
                ON CONFLICT (role_id, required_role_id) DO NOTHING
                """,
                tuple((role_id, other_id) for other_id in req_role_ids),
            )

    @staticmethod
    def set_req_all(
        conn: apsw.Connection, guild_id: int, role_id: int, *req_role_ids: int
    ):
        total_role_ids = {
            role_id,
            *req_role_ids,
        }
        with contextlib.closing(conn.cursor()) as cursor, conn:
            cursor.execute(
                """
                INSERT INTO guild_settings (guild_id) VALUES (?)
                ON CONFLICT (guild_id) DO NOTHING
                """,
                (guild_id,),
            )
            cursor.executemany(
                """
                INSERT INTO role_settings (role_id, guild_id) VALUES (?,?)
                ON CONFLICT (role_id) DO NOTHING
                """,
                tuple((rid, guild_id) for rid in total_role_ids),
            )
            cursor.execute(
                """
                DELETE FROM role_requires_all WHERE role_id = ?
                """,
                (role_id,),
            )
            cursor.executemany(
                """
                INSERT INTO role_requires_all (role_id, required_role_id) VALUES (?,?)
                ON CONFLICT (role_id, required_role_id) DO NOTHING
                """,
                tuple((role_id, other_id) for other_id in req_role_ids),
            )

    @classmethod
    def from_databse(cls, conn: apsw.Connection, role_id: int, guild_id: int):

        cursor = conn.cursor()

        row = cursor.execute(
            """
            SELECT self_assignable, self_removable, sticky
            FROM role_settings
            WHERE role_id = ? AND guild_id = ?
            """,
            (role_id, guild_id),
        ).fetchone()

        if not row:
            raise NoSuchRecord()

        self_assignable, self_removable, sticky = row

        exclusive_roles = tuple(
            r[0]
            for r in cursor.execute(
                """
                WITH
                    lower_part AS (
                        SELECT role_id_1 AS rid
                        FROM role_mutual_exclusivity
                        WHERE role_id_2 = :role_id
                    ),
                    upper_part AS (
                        SELECT role_id_2 AS rid
                        FROM role_mutual_exclusivity
                        WHERE role_id_1 = :role_id
                    )
                SELECT * FROM lower_part
                UNION ALL
                SELECT * FROM upper_part
                """,
                dict(role_id=role_id),
            )
        )

        require_any = tuple(
            r[0]
            for r in cursor.execute(
                """
                SELECT required_role_id FROM role_requires_any
                WHERE role_id = ?
                """,
                (role_id,),
            )
        )

        require_all = tuple(
            r[0]
            for r in cursor.execute(
                """
                SELECT required_role_id FROM role_requires_all
                WHERE role_id = ?
                """,
                (role_id,),
            )
        )

        return cls(
            role_id,
            guild_id,
            self_assignable,
            self_removable,
            sticky,
            exclusive_roles,
            require_any,
            require_all,
        )
