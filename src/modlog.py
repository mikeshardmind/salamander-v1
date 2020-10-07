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

import apsw
import discord
import msgpack

from .utils import MainThreadSingletonMeta as Singleton

EMPTY_MAP = b"\x80"

##########################################################################################
# Schema for modlog in db, payload is a messagepack'd dict                               #
##########################################################################################
#   CREATE TABLE IF NOT EXISTS mod_log (                                                 #
#   	mod_action TEXT NOT NULL,                                                        #
#   	mod_id INTEGER NOT NULL,                                                         #
#   	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)                    #
#   		ON UPDATE CASCADE ON DELETE CASCADE,                                         #
#   	target_id INTEGER NOT NULL,                                                      #
#   	created_at DEFAULT CURRENT_TIMESTAMP,                                            #
#       reason TEXT,                                                                     #
#   	payload,                                                                         #
#   	username_at_action TEXT,                                                         #
#   	discrim_at_action TEXT,                                                          #
#   	nick_at_action TEXT,                                                             #
#   	FOREIGN KEY (mod_id, guild_id) REFERENCES member_settings (user_id, guild_id)    #
#   		ON UPDATE CASCADE ON DELETE RESTRICT,                                        #
#   	FOREIGN KEY (target_id, guild_id) REFERENCES member_settings (user_id, guild_id) #
#   		ON UPDATE CASCADE ON DELETE RESTRICT                                         #
#   );                                                                                   #
##########################################################################################
#   Referenced Table: member_settings                                                    #
##########################################################################################
#   CREATE TABLE IF NOT EXISTS member_settings (                                         #
#   	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)                    #
#   		ON UPDATE CASCADE ON DELETE CASCADE,                                         #
#   	user_id INTEGER NOT NULL REFERENCES user_settings(user_id)                       #
#   		ON UPDATE CASCADE ON DELETE CASCADE,                                         #
#   	is_blacklisted BOOLEAN DEFAULT false,                                            #
#   	is_mod BOOLEAN DEFAULT false,                                                    #
#   	is_admin BOOLEAN DEFAULT false,                                                  #
#   	last_known_nick TEXT DEFAULT NULL,                                               #
#   	PRIMARY KEY (user_id, guild_id)                                                  #
#   );                                                                                   #
##########################################################################################
# Referenced Table: user_settings                                                        #
##########################################################################################
#   CREATE TABLE IF NOT EXISTS user_settings (                                           #
#   	user_id INTEGER PRIMARY KEY NOT NULL,                                            #
#   	is_bot_vip BOOLEAN DEFAULT false,                                                #
#   	is_network_admin BOOLEAN DEFAULT false,                                          #
#   	timezone TEXT DEFAULT NULL,                                                      #
#   	timezone_is_public BOOLEAN DEFAULT false,                                        #
#   	is_blacklisted BOOLEAN DEFAULT false,                                            #
#   	last_known_name TEXT DEFAULT NULL,                                               #
#   	last_known_discrim TEXT DEFAULT NULL,                                            #
#   	anon DEFAULT false                                                               #
#   );                                                                                   #
##########################################################################################

# Statements which get used for multiple functions here

INSERT_USER_ID = """
INSERT INTO user_settings (user_id)
VALUES (?)
ON CONFLICT (user_id) DO NOTHING
"""

INSERT_MEMBER_IDS = """
INSERT INTO member_settings (user_id, guild_id)
VALUES (?, ?)
ON CONFLICT (user_id, guild_id) DO NOTHING
"""

INSERT_OR_UPDATE_USER = """
INSERT INTO user_settings (user_id, last_known_name, last_known_discrim)
VALUES (?,?,?)
ON CONFLICT (user_id)
DO UPDATE SET
    last_known_name=excluded.last_known_name,
    last_known_discrim=excluded.last_known_discrim
"""

INSERT_OR_IGNORE_GUILD = """
INSERT INTO guild_settings (guild_id) VALUES (?)
ON CONFLICT (guild_id) DO NOTHING
"""

INSERT_OR_UPDATE_MEMBER = """
INSERT INTO member_settings (user_id, guild_id, last_known_nick)
VALUES (?,?,?)
ON CONFLICT (user_id, guild_id)
DO UPDATE SET
    last_known_nick=excluded.last_known_nick
"""

BASIC_MODLOG_INSERT = """
INSERT INTO mod_log (
    mod_action,
    mod_id,
    guild_id,
    target_id,
    reason,
    username_at_action,
    discrim_at_action,
    nick_at_action,
    payload
)
VALUES (
    :action_name,
    :mod_id,
    :guild_id,
    :target_id,
    :reason,
    :username,
    :discrim,
    :nick,
    :payload,
)
"""


class ModlogHandler(metaclass=Singleton):
    def __init__(self, connection: apsw.Connection):
        self._conn: apsw.Connection = connection
        with contextlib.closing(self._conn.cursor()) as cursor:
            cursor.execute(""" PRAGMA foreign_keys=ON """)

    def member_kick(self, mod: discord.Member, target: discord.Member, reason: str):

        with contextlib.closing(self._conn.cursor()) as cursor, self._conn:
            guild_id = mod.guild.id

            cursor.executemany(
                INSERT_OR_UPDATE_USER,
                (
                    (target.id, target.name, target.discriminator),
                    (mod.id, mod.name, mod.discriminator),
                ),
            )
            cursor.execute(
                INSERT_OR_IGNORE_GUILD, (guild_id,),
            )
            cursor.executemany(
                INSERT_OR_UPDATE_MEMBER,
                ((target.id, guild_id, target.nick), (mod.id, guild_id, mod.nick)),
            )
            cursor.execute(
                BASIC_MODLOG_INSERT,
                dict(
                    action_name="KICK",
                    mod_id=mod.id,
                    guild_id=guild_id,
                    target_id=target.id,
                    reason=reason,
                    username=target.name,
                    discrim=target.discriminator,
                    nick=target.nick,
                    payload=EMPTY_MAP,
                ),
            )

    def member_ban(self, mod: discord.Member, target: discord.Member, reason: str):

        with contextlib.closing(self._conn.cursor()) as cursor, self._conn:
            guild_id = mod.guild.id

            cursor.executemany(
                INSERT_OR_UPDATE_USER,
                (
                    (target.id, target.name, target.discriminator),
                    (mod.id, mod.name, mod.discriminator),
                ),
            )
            cursor.execute(
                INSERT_OR_IGNORE_GUILD, (guild_id,),
            )
            cursor.executemany(
                INSERT_OR_UPDATE_MEMBER,
                ((target.id, guild_id, target.nick), (mod.id, guild_id, mod.nick)),
            )
            cursor.execute(
                BASIC_MODLOG_INSERT,
                dict(
                    action_name="BAN",
                    mod_id=mod.id,
                    guild_id=guild_id,
                    target_id=target.id,
                    reason=reason,
                    username=target.name,
                    discrim=target.discriminator,
                    nick=target.nick,
                    payload=EMPTY_MAP,
                ),
            )

    def member_muted(self, mod: discord.Member, target: discord.Member, reason: str):
        with contextlib.closing(self._conn.cursor()) as cursor, self._conn:
            guild_id = mod.guild.id

            cursor.executemany(
                INSERT_OR_UPDATE_USER,
                (
                    (target.id, target.name, target.discriminator),
                    (mod.id, mod.name, mod.discriminator),
                ),
            )
            cursor.execute(
                INSERT_OR_IGNORE_GUILD, (guild_id,),
            )
            cursor.executemany(
                INSERT_OR_UPDATE_MEMBER,
                ((target.id, guild_id, target.nick), (mod.id, guild_id, mod.nick)),
            )
            cursor.execute(
                BASIC_MODLOG_INSERT,
                dict(
                    action_name="MUTE",
                    mod_id=mod.id,
                    guild_id=guild_id,
                    target_id=target.id,
                    reason=reason,
                    username=target.name,
                    discrim=target.discriminator,
                    nick=target.nick,
                    payload=EMPTY_MAP,
                ),
            )

    def member_unmuted(self, mod: discord.Member, target: discord.Member, reason: str):
        with contextlib.closing(self._conn.cursor()) as cursor, self._conn:
            guild_id = mod.guild.id

            cursor.executemany(
                INSERT_OR_UPDATE_USER,
                (
                    (target.id, target.name, target.discriminator),
                    (mod.id, mod.name, mod.discriminator),
                ),
            )
            cursor.execute(
                INSERT_OR_IGNORE_GUILD, (guild_id,),
            )
            cursor.executemany(
                INSERT_OR_UPDATE_MEMBER,
                ((target.id, guild_id, target.nick), (mod.id, guild_id, mod.nick)),
            )
            cursor.execute(
                BASIC_MODLOG_INSERT,
                dict(
                    action_name="UNMUTE",
                    mod_id=mod.id,
                    guild_id=guild_id,
                    target_id=target.id,
                    reason=reason,
                    username=target.name,
                    discrim=target.discriminator,
                    nick=target.nick,
                    payload=EMPTY_MAP,
                ),
            )

    def member_tempmuted(
        self, mod: discord.Member, target: discord.Member, reason: str, duration: float
    ):
        with contextlib.closing(self._conn.cursor()) as cursor, self._conn:
            guild_id = mod.guild.id

            cursor.executemany(
                INSERT_OR_UPDATE_USER,
                (
                    (target.id, target.name, target.discriminator),
                    (mod.id, mod.name, mod.discriminator),
                ),
            )
            cursor.execute(
                INSERT_OR_IGNORE_GUILD, (guild_id,),
            )
            cursor.executemany(
                INSERT_OR_UPDATE_MEMBER,
                ((target.id, guild_id, target.nick), (mod.id, guild_id, mod.nick)),
            )
            cursor.execute(
                BASIC_MODLOG_INSERT,
                dict(
                    action_name="TEMPMUTE",
                    mod_id=mod.id,
                    guild_id=guild_id,
                    target_id=target.id,
                    reason=reason,
                    username=target.name,
                    discrim=target.discriminator,
                    nick=target.nick,
                    payload=msgpack.packb({"duration": duration}),
                ),
            )

    def user_ban(self, mod: discord.Member, target_id: int, reason: str):

        with contextlib.closing(self._conn.cursor()) as cursor, self._conn:
            guild_id = mod.guild.id
            cursor.execute(INSERT_USER_ID, (target_id,))
            cursor.execute(
                INSERT_OR_UPDATE_USER, (mod.id, mod.name, mod.discriminator),
            )
            cursor.execute(
                INSERT_OR_IGNORE_GUILD, (guild_id,),
            )
            cursor.execute(INSERT_MEMBER_IDS, (target_id, guild_id))
            cursor.execute(
                INSERT_OR_UPDATE_MEMBER, (mod.id, guild_id, mod.nick),
            )
            cursor.execute(
                BASIC_MODLOG_INSERT,
                dict(
                    action_name="HACKBAN",
                    mod_id=mod.id,
                    guild_id=guild_id,
                    target_id=target_id,
                    reason=reason,
                    username="",
                    discrim="",
                    nick="",
                    payload=EMPTY_MAP,
                ),
            )
