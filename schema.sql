--   Copyright 2020-present Michael Hall
--
--   Licensed under the Apache License, Version 2.0 (the "License");
--   you may not use this file except in compliance with the License.
--   You may obtain a copy of the License at
--
--       http://www.apache.org/licenses/LICENSE-2.0
--
--   Unless required by applicable law or agreed to in writing, software
--   distributed under the License is distributed on an "AS IS" BASIS,
--   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
--   See the License for the specific language governing permissions and
--   limitations under the License.


-- sql here intended for sqlite >= 3.35.4 (RETURNING being the newest feature used)
-- timezones are stored using the IANA code, not a raw offset
-- discord and bot event timestamps use unix timestamps,
-- any user displays for these are then formed by
-- forming an appropriate date using the user's configured timezone

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA wal_autocheckpoint = 1000;
PRAGMA journal_size_limit = -1;


-- BEGIN REGION: Core bot settings

-- feature flags is a bitfield which supports future growth in 1 column.
-- Filter via basalisk's networkwide settings: 1
CREATE TABLE IF NOT EXISTS guild_settings (
	guild_id INTEGER PRIMARY KEY NOT NULL,
	mute_role INTEGER DEFAULT NULL,
	timezone TEXT DEFAULT 'America/New_York',
	mod_log_channel INTEGER DEFAULT NULL,
	feature_flags INTEGER DEFAULT 0
);

BEGIN;
CREATE TABLE IF NOT EXISTS guild_settings_modadmin_migration (
	guild_id INTEGER PRIMARY KEY NOT NULL,
	mute_role INTEGER DEFAULT NULL,
	mod_role INTEGER DEFAULT NULL,
	admin_role INTEGER DEFAULT NULL,
	timezone TEXT DEFAULT 'America/New_York',
	mod_log_channel INTEGER DEFAULT NULL,
	feature_flags INTEGER DEFAULT 0
);

INSERT INTO guild_settings_modadmin_migration (
	guild_id, mute_role, timezone, mod_log_channel, feature_flags
)
SELECT
	guild_id, mute_role, timezone, mod_log_channel, feature_flags
FROM guild_settings;

DROP TABLE guild_settings;
ALTER TABLE guild_settings_modadmin_migration RENAME TO guild_settings;
COMMIT;



-- annoyance filters
-- These are behavioral things to be dealt with automatically.
CREATE TABLE IF NOT EXISTS annoyance_filter_settings (
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id),
	mods_immune BOOLEAN DEFAULT false,
	admins_immune BOOLEAN DEFAULT false,
	remove_apngs BOOLEAN DEFAULT false,
	remove_excessive_html_elements BOOLEAN DEFAULT false,
	PRIMARY KEY (guild_id)
);


-- 0 indicates inactive
-- interval length is seconds
-- mute duration is minutes, 
-- with 0 combined with an active mute indicating a non-temporary mute
CREATE TABLE IF NOT EXISTS antimentionspam_settings (
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id),
	max_mentions_single INTEGER DEFAULT 0,
	max_mentions_interval INTEGER DEFAULT 0,
	interval_length INTEGER DEFAULT 0,
	warn_message TEXT DEFAULT '',
	mute BOOLEAN DEFAULT FALSE,
	mute_duration INTEGER DEFAULT 0,
	ban BOOLEAN DEFAULT FALSE,
	ban_single BOOLEAN DEFAULT FALSE,
	PRIMARY KEY (guild_id)
);


-- Primary key here is a cute way of getting both a 
-- covering index and a unique constraint for (guild_id, prefix) as a two in one.
CREATE TABLE IF NOT EXISTS guild_prefixes (
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id),
	prefix TEXT NOT NULL,
	PRIMARY KEY (guild_id, prefix)
);

-- This can be merged into the above in a future version,
-- we're doing this for the few current users of a beta to be able to give feedback
-- without this next set of changes wrecking them entirely.
-- adding constraints on the db side to prep the schema for architecture changes
-- This is only to avoid consistency issues, frontend should still check each of these conditions
-- individually to get a specific failure case to present to end users
--  The set Markdown with specific meaning
--  { "*", "`", "_", "~", "|", ">>>", "'", '"', "\" }
-- The set of disallowed string prefixes for specific reasons:
-- "/" slash commands
-- Additionally, any prefix above 15 characters or which constains <...> will be rejected
BEGIN;
CREATE TABLE IF NOT EXISTS guild_prefixes_constraint_migration (
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id),
	prefix TEXT NOT NULL CHECK(
		length(prefix) < 16
		AND NOT prefix LIKE '%:%'
		AND NOT prefix LIKE '%<%>%'
		AND NOT prefix LIKE '/%' 
		AND NOT prefix LIKE '%~*%' ESCAPE '~'
		AND NOT prefix LIKE '%\%'
		AND NOT prefix LIKE '%`%'
		AND NOT prefix LIKE '%~_%' ESCAPE '~'
		AND NOT prefix LIKE '%~%'
		AND NOT prefix LIKE '%|%'
		AND NOT prefix LIKE '%> %'
		AND NOT prefix LIKE '%''%'
		AND NOT prefix LIKE '%"%'
	),
	PRIMARY KEY (guild_id, prefix)
);

INSERT INTO guild_prefixes_constraint_migration 
	SELECT * FROM guild_prefixes
	WHERE
		length(prefix) < 16
		AND NOT prefix LIKE '%:%'
		AND NOT prefix LIKE '%<%>%'
		AND NOT prefix LIKE '/%' 
		AND NOT prefix LIKE '%~*%' ESCAPE '~'
		AND NOT prefix LIKE '%\%'
		AND NOT prefix LIKE '%`%'
		AND NOT prefix LIKE '%~_%' ESCAPE '~'
		AND NOT prefix LIKE '%~%'
		AND NOT prefix LIKE '%|%'
		AND NOT prefix LIKE '%> %'
		AND NOT prefix LIKE '%''%'
		AND NOT prefix LIKE '%"%';
DROP TABLE guild_prefixes;
ALTER TABLE guild_prefixes_constraint_migration RENAME TO guild_prefixes;
COMMIT;


-- anon: represents whether the user_id was intentionally set to an invalid snowflake to keep referential integrity
-- This is not used outside of requests from discord to remove a deleted user.
-- In the event of deleting a user,
-- the user will instead be anonymized and any data which could identify them reset to defaults
CREATE TABLE IF NOT EXISTS user_settings (
	user_id INTEGER PRIMARY KEY NOT NULL,
	is_bot_vip BOOLEAN DEFAULT false,
	is_network_admin BOOLEAN DEFAULT false,
	timezone TEXT DEFAULT NULL,
	timezone_is_public BOOLEAN DEFAULT false,
	is_blocked BOOLEAN DEFAULT false,
	anon DEFAULT false
);


CREATE TABLE IF NOT EXISTS member_settings (
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	user_id INTEGER NOT NULL REFERENCES user_settings(user_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	is_blocked BOOLEAN DEFAULT false,
	is_mod BOOLEAN DEFAULT false,
	is_admin BOOLEAN DEFAULT false,
	PRIMARY KEY (user_id, guild_id)
);


CREATE TABLE IF NOT EXISTS mod_log (
	mod_action TEXT NOT NULL,
	mod_id INTEGER NOT NULL,
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	target_id INTEGER NOT NULL,
	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
	reason TEXT,
	username_at_action TEXT,
	discrim_at_action TEXT,
	nick_at_action TEXT,
	FOREIGN KEY (mod_id, guild_id) REFERENCES member_settings (user_id, guild_id)
		ON UPDATE CASCADE ON DELETE RESTRICT,
	FOREIGN KEY (target_id, guild_id) REFERENCES member_settings (user_id, guild_id)
		ON UPDATE CASCADE ON DELETE RESTRICT
);

-- END REGION

-- BEGIN REGION: Mutes

-- We can't allow self deletion of users via GDPR
-- who we need to know if they rejoin a server to attempt dodging a mute,
-- the restriction on deletion is appropriate here
CREATE TABLE IF NOT EXISTS guild_mutes (
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	user_id INTEGER NOT NULL,
	muted_at TEXT DEFAULT CURRENT_TIMESTAMP,
	expires_at TEXT DEFAULT NULL,
    mute_role_used INTEGER, 
	FOREIGN KEY (user_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON UPDATE CASCADE ON DELETE RESTRICT,
	PRIMARY KEY (user_id, guild_id)
);


CREATE TABLE IF NOT EXISTS guild_mute_removed_roles (
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	user_id INTEGER NOT NULL,
	removed_role_id INTEGER NOT NULL,
	FOREIGN KEY (user_id, guild_id) REFERENCES guild_mutes(user_id, guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	UNIQUE(guild_id, user_id, removed_role_id)
);

-- END REGION

-- BEGIN REGION: Knowledgebase

-- this data is explicitly given to the bot
-- for the express purpose of allowing it to be reposted by the bot in the guild it was provided
-- We allow anonymizing the original owner, effectively decoupling them from the data
-- but not deletion or breaking referential integrity
CREATE TABLE IF NOT EXISTS guild_kb_entries (
	guild_id REFERENCES guild_settings (guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	user_id INTEGER,
	kb_article_name TEXT,
	content TEXT,
	times_used INTEGER DEFAULT 0,
	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY (user_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON DELETE RESTRICT ON UPDATE CASCADE,
	PRIMARY KEY (kb_article_name, guild_id)
);

-- END REGION

-- BEGIN REGION: warnings

CREATE TABLE IF NOT EXISTS guild_warnings (
	guild_id INTEGER REFERENCES guild_settings(guild_id)
		ON DELETE CASCADE ON UPDATE CASCADE,
	user_id INTEGER,
	mod_id INTEGER,
	reason TEXT DEFAULT NULL,
	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY(mod_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON UPDATE CASCADE ON DELETE RESTRICT,
	FOREIGN KEY (user_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON UPDATE CASCADE ON DELETE RESTRICT
);

-- END REGION

-- Similar to tags, this is data provided to the bot for the express purpose of resending
-- However, as this is notes about specific users,
-- if the user no longer exists, the data is no longer needed.
CREATE TABLE IF NOT EXISTS mod_notes_on_members (
	guild_id INTEGER REFERENCES guild_settings(guild_id)
		ON DELETE CASCADE ON UPDATE CASCADE,
	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
	mod_id INTEGER,
	target_id INTEGER,
	note TEXT NOT NULL,
	FOREIGN KEY (mod_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON UPDATE CASCADE ON DELETE RESTRICT,
	FOREIGN KEY (target_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE
);


-- BEGIN REGION: Role Management

CREATE TABLE IF NOT EXISTS role_settings (
	role_id INTEGER PRIMARY KEY NOT NULL,
	guild_id INTEGER REFERENCES guild_settings(guild_id)
		ON DELETE CASCADE ON UPDATE CASCADE,
	self_assignable BOOLEAN DEFAULT false,
	self_removable BOOLEAN DEFAULT false,
	sticky BOOLEAN DEFAULT false
);

CREATE TABLE IF NOT EXISTS roles_stuck_to_members (
	role_id INTEGER NOT NULL REFERENCES role_settings(role_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	user_id INTEGER NOT NULL,
	FOREIGN KEY (user_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	PRIMARY KEY(guild_id, user_id, role_id)
);

CREATE TABLE IF NOT EXISTS react_role_entries (
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	channel_id INTEGER NOT NULL,
	message_id INTEGER NOT NULL,
	reaction_string TEXT NOT NULL,
	role_id INTEGER REFERENCES role_settings(role_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	react_remove_triggers_removal BOOLEAN DEFAULT false,
	PRIMARY KEY (message_id, reaction_string)
);

CREATE TABLE IF NOT EXISTS role_mutual_exclusivity (
	role_id_1 INTEGER NOT NULL REFERENCES role_settings(role_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	role_id_2 INTEGER NOT NULL REFERENCES role_settings(role_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	PRIMARY KEY (role_id_1, role_id_2),
	CHECK (role_id_1 < role_id_2)
);

CREATE TABLE IF NOT EXISTS role_requires_any (
	role_id INTEGER NOT NULL REFERENCES role_settings(role_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	required_role_id INTEGER NOT NULL REFERENCES role_settings(role_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	PRIMARY KEY (role_id, required_role_id)
);

CREATE TABLE IF NOT EXISTS role_requires_all (
	role_id INTEGER NOT NULL REFERENCES role_settings(role_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	required_role_id INTEGER NOT NULL REFERENCES role_settings(role_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	PRIMARY KEY (role_id, required_role_id)
);

-- END REGION

-- BEGIN REGION: feedback system
-- This won't be anabled by default

CREATE TABLE IF NOT EXISTS feedback_types (
	feedback_type TEXT PRIMARY KEY NOT NULL,
	destination_id INTEGER DEFAULT NULL,
	autoresponse TEXT DEFAULT NULL
);


-- repr status won't be user facing immediately, but soon enough that it's worth including here now
CREATE TABLE IF NOT EXISTS feedback_entries (
	user_id INTEGER REFERENCES user_settings(user_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	feedback_type TEXT REFERENCES feedback_types(feedback_type)
		ON UPDATE CASCADE ON DELETE CASCADE,
	uuid TEXT PRIMARY KEY NOT NULL,
	repr_status TEXT DEFAULT 'unknown',
	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
	feedback TEXT NOT NULL
);
