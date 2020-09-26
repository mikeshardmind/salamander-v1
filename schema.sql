--   Copyright 2020 Michael Hall
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


-- sql here intended for sqlite
-- timezones are stored using the IANA code, not a raw offset
-- discord and bot event timestamps use unix timestamps,
-- any user displays for these are then formed by
-- forming an appropriate date using the user's configured timezone

PRAGMA foreign_keys=ON;

-- BEGIN REGION: Core bot settings

-- prefixes is a tuple, stored in sqlite as a blob after serializing using msgpack
-- feature flags is a bitfield reserved for some future plans for enabling specific features per guild
CREATE TABLE IF NOT EXISTS guild_settings (
	guild_id INTEGER PRIMARY KEY NOT NULL,
	is_blacklisted BOOLEAN DEFAULT false,
	mute_role INTEGER DEFAULT NULL,
	prefixes DEFAULT NULL,
	locale TEXT DEFAULT "en-US",
	timezone TEXT DEFAULT "America/New_York",
	mod_log_channel INTEGER DEFAULT 0,
	announcement_channel INTEGER DEFAULT 0,
	telemetry_opt_in BOOLEAN DEFAULT false,
	bot_color INTEGER DEFAULT NULL,
	feature_flags INTEGER DEFAULT 0
);


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
	is_blacklisted BOOLEAN DEFAULT false,
	last_known_name TEXT DEFAULT NULL,
	last_known_discrim TEXT DEFAULT NULL,
	anon DEFAULT false
);


CREATE TABLE IF NOT EXISTS member_settings (
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	user_id INTEGER NOT NULL REFERENCES user_settings(user_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	is_blacklisted BOOLEAN DEFAULT false,
	is_mod BOOLEAN DEFAULT false,
	is_admin BOOLEAN DEFAULT false,
	last_known_nick TEXT DEFAULT NULL,
	PRIMARY KEY (user_id, guild_id)
);


CREATE TABLE IF NOT EXISTS channel_settings (
	channel_id INTEGER NOT NULL PRIMARY KEY,
	is_ignored BOOLEAN DEFAULT false,
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
		ON DELETE CASCADE ON UPDATE CASCADE
);

-- payload here is a python dictionary which has been serialized via msgpack
-- The structure of the dictionary is dependant on the action, but is only used for
-- direct interactions in discord, and does not need to be handled by the DB
-- username, discrim, and nick at time of action are stored in the DB rather than payload.
-- This allows this specific information to be stripped from the db without the DB needing understanding of
-- the discord specific payload related to information about the mod action itself,
-- not the moderation target (for use in displays)
CREATE TABLE IF NOT EXISTS mod_log (
	mod_action TEXT NOT NULL,
	mod_id INTEGER NOT NULL,
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	target_id INTEGER NOT NULL,
	created_at DEFAULT CURRENT_TIMESTAMP,
	reason TEXT,
	payload,
	username_at_action TEXT,
	discrim_at_action TEXT,
	nick_at_action TEXT,
	FOREIGN KEY (mod_id, guild_id) REFERENCES member_settings (user_id, guild_id)
		ON UPDATE CASCADE ON DELETE RESTRICT,
	FOREIGN KEY (target_id, guild_id) REFERENCES member_settings (user_id, guild_id)
		ON UPDATE CASCADE ON DELETE RESTRICT
);

-- Indexes for the two common lookup cases
CREATE INDEX IF NOT EXISTS modlog_targets ON mod_log (target_id, guild_id);
CREATE INDEX IF NOT EXISTS modlog_moderators ON mod_log (mod_id, guild_id);

-- END REGION

-- BEGIN REGION: Mutes

-- We can't allow self deletion of users via GDPR
-- who we need to know if they rejoin a server to attempt dodging a mute,
-- the restriction on deletion is appropriate here
-- removed_roles: this is a msgpack list of ids used for undoing the mute later on
CREATE TABLE IF NOT EXISTS guild_mutes (
	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	user_id INTEGER NOT NULL,
	muted_at DEFAULT CURRENT_TIMESTAMP,
	expires_at DEFAULT NULL,
    mute_role_used INTEGER, 
    removed_roles,
	FOREIGN KEY (user_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON UPDATE CASCADE ON DELETE RESTRICT,
	PRIMARY KEY (user_id, guild_id)
);

-- END REGION

-- BEGIN REGION: User generated tags

-- tag data is data explicitly given to the bot
-- for the express purpose of allowing it to be reposted by the bot in the guild it was provided
-- We allow anonymizing the original owner, effectively decoupling them from the data
-- but not deletion or breaking referential integrity
CREATE TABLE IF NOT EXISTS user_tags (
	guild_id REFERENCES guild_settings (guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	user_id INTEGER,
	tag_name TEXT,
	response TEXT,
	times_used INTEGER default 0,
	FOREIGN KEY (user_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON DELETE RESTRICT ON UPDATE CASCADE,
	PRIMARY KEY (tag_name, guild_id)
);


-- embed payload is a msgpack serialized python dict suitable for turning into a discord embed object
CREATE TABLE IF NOT EXISTS user_embed_tags (
	guild_id REFERENCES guild_settings (guild_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	user_id INTEGER,
	tag_name TEXT,
	embed_payload,
	times_used INTEGER default 0,
	FOREIGN KEY (user_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON DELETE RESTRICT ON UPDATE CASCADE,
	PRIMARY KEY (tag_name, guild_id)
);


-- the below tags don't store specific metadata and are only able to be created or modified by the bot owner
CREATE TABLE IF NOT EXISTS global_text_tags (
	tag_name TEXT NOT NULL PRIMARY KEY,
	response TEXT
);


-- embed payload is a msgpack serialized python dict suitable for turning into a discord embed object
CREATE TABLE IF NOT EXISTS global_embed_tags (
	tag_name TEXT NOT NULL PRIMARY KEY,
	embed_payload
);


-- TODO(future considerations) consider FTS virtual table for fast lookup of similar tags
-- This isn't part of the original design at all, and only exact tags will be matched

-- END REGION

-- BEGIN REGION: REPORT TOOLS
-- TODO(design)
-- END REGION

-- BEGIN REGION: warnings

CREATE TABLE IF NOT EXISTS guild_warnings (
	guild_id INTEGER REFERENCES guild_settings(guild_id)
		ON DELETE CASCADE ON UPDATE CASCADE,
	user_id INTEGER,
	mod_id INTEGER,
	reason TEXT DEFAULT NULL,
	FOREIGN KEY(mod_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON DELETE RESTRICT ON UPDATE CASCADE,
	FOREIGN KEY (user_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS warning_targets on guild_warnings (user_id, guild_id);
CREATE INDEX IF NOT EXISTS warning_mods on guild_warnings (mod_id, guild_id);

-- END REGION

-- Similar to tags, this is data provided to the bot for the express purpose of resending
-- However, as this is notes about specific users,
-- if the user no longer exists, the data is no longer needed.
CREATE TABLE IF NOT EXISTS mod_user_notes (
	guild_id INTEGER REFERENCES guild_settings(guild_id)
		ON DELETE CASCADE ON UPDATE CASCADE,
	created_at INTEGER DEFAULT CURRENT_TIMESTAMP,
	mod_id INTEGER,
	target_id INTEGER,
	note TEXT NOT NULL,
	FOREIGN KEY (mod_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON DELETE CASCADE ON UPDATE CASCADE,
	FOREIGN KEY (target_id, guild_id) REFERENCES member_settings(user_id, guild_id)
		ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS modnote_targets ON mod_user_notes (target_id, guild_id);
CREATE INDEX IF NOT EXISTS modnote_moderators ON mod_user_notes (mod_id, guild_id);


-- BEGIN REGION: Role assignments (region commented out until I'm more sure about some of this)

-- some of the queries for this section may start getting a little complex,
-- I'm fine with dropping some of this functionality if it becomes a concern

-- 
-- 
-- CREATE TABLE IF NOT EXISTS role_settings (
-- 	role_id INTEGER NOT NULL PRIMARY KEY,
-- 	guild_id INTEGER REFERENCES guild_settings(guild_id)
-- 		ON UPDATE CASCADE ON DELETE CASCADE,
-- 	self_assignable BOOLEAN DEFAULT false,
-- 	self_removable BOOLEAN DEFAULT false,
-- 	auto_role BOOLEAN DEFAULT false
-- );
-- 
-- CREATE TABLE IF NOT EXISTS react_role (
-- 	message_id INTEGER NOT NULL,
-- 	channel_id INTEGER NOT NULL,
-- 	reaction TEXT NOT NULL,
-- 	guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE,
-- 	role_id INTEGER REFERENCES role_settings(role_id)
-- 		ON DELETE CASCADE ON UPDATE ,
-- 	PRIMARY KEY (message_id, reaction)
-- );
-- 
-- -- no_drop_below is for preventing self removal of roles which would drop a user below n roles in group
-- -- Useful for things such requiring selecting a team from a number of teams
-- -- max_allowed is defaulted at above the number of roles a discord guild can have, by a significant margin
-- -- Use case is for signing up for a limited number of activites at once via role
-- CREATE TABLE IF NOT EXISTS role_groups (
-- 	group_name TEXT NOT NULL,
-- 	guild_id INTEGER REFERENCES guild_settings(guild_id)
-- 		ON UPDATE CASCADE ON DELETE CASCADE,
-- 	no_drop_below INTEGER DEFAULT 0,
-- 	max_allowed INTEGER DEFAULT 4096,
-- 	PRIMARY KEY (group_name, guild_id)
-- );
-- 
-- 
-- CREATE TABLE IF NOT EXISTS role_group_membership (
-- 	group_name TEXT NOT NULL,
-- 	guild_id INTEGER NOT NULL,
-- 	role_id INTEGER REFERENCES role_settings(role_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE,
-- 	in_group BOOLEAN DEFAULT false,
-- 	FOREIGN KEY (group_name, guild_id) REFERENCES role_groups(group_name, guild_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE
-- );
-- 
-- -- Below tables are used instead of a msgpack list of IDs, should sqlite add array type support
-- -- at a later date, this may be changed to just be part of the above tables
-- 
-- CREATE TABLE IF NOT EXISTS role_assign_requirements (
-- 	role_id INTEGER REFERENCES role_settings(role_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE,
-- 	required_role_id INTEGER REFERENCES role_settings(role_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE
-- 	is_required BOOLEAN DEFAULT false
-- );
-- 
-- 
-- CREATE TABLE IF NOT EXISTS role_assign_ignored_roles (
-- 	role_id INTEGER REFERENCES role_settings(role_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE,
-- 	required_role_id INTEGER REFERENCES role_settings(role_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE,
-- 	is_ignored BOOLEAN DEFAULT false
-- );
-- 
-- 
-- CREATE TABLE IF NOT EXISTS role_group_assign_requirements (
-- 	group_name TEXT,
-- 	guild_id INTEGER,
-- 	is_required BOOLEAN false,
-- 	required_role_id INTEGER REFERENCES role_settings(role_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE,
-- 	FOREIGN KEY (group_name, guild_id) REFERENCES role_groups(group_name, guild_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE 
-- );
-- 
-- 
-- CREATE TABLE IF NOT EXISTS role_group_assign_ignored_roles (
-- 	group_name TEXT,
-- 	guild_id INTEGER,
-- 	is_ignored BOOLEAN false,
-- 	required_role_id INTEGER REFERENCES role_settings(role_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE,
-- 	FOREIGN KEY (group_name, guild_id) REFERENCES role_groups(group_name, guild_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE
-- );
-- 
-- -- END REGION

-- BEGIN REGION: Command availability model (commented out for more consideration before committing to this.)

-- Understanding this section requires a bit of info about the command availability model
-- To summarize, commands eligible for modification by user set rules
-- have defaults of being available to:
--     - Everyone in a guild
--     - Mods
--     - Admins
--     - Guild owner

-- Commands which are bot owner or network admin only may not be modified here,
-- these restrictions are considered for safety.
-- Additionally, commands which are used to configure this are administrator only and can not be modified
-- subcommands do not implictly allow parent commands,
-- though command layout has been designed to limit the cases where 
-- users want to give access to some subcommands and not others. Additionally, command groups which act as
-- anything more than a help command for the group
-- have been disallowed in the project for consideration to reduce the
-- cognitive overhead for people considering their permission layouts

-- Beyond this, we allow the following levels of changes per guild:
-- 1. Changing the default to a more restrictive default level.
-- 2. If and only if we have access to the member update intent(discord limitation), Adding a role requirement.
-- 3. If and only if a role requirement has been added, chaning the default to a less restrctive default.
-- 4. Granularly allowing specific users access to a command.
-- 5. Disabling a command in a guild.

-- We do not allow restricting specific users, in case of abuse by users, 
-- we reccomend blacklisting the user entirely or banning the user outright

-- lookups are significantly more common than modifications, 
-- the primary key is chosen for lookup performance

--  CREATE TABLE IF NOT EXISTS permission_model_default_rules (
-- 	command TEXT NOT NULL,
-- 	guild_id INTEGER REFERENCES guild_settings(guild_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE,
-- 	level_modified_to TEXT DEFAULT NULL,
-- 	requires_role INTEGER DEFAULT NULL,
-- 	is_disabled BOOLEAN DEFAULT false,
-- 	PRIMARY KEY (guild_id, command)
-- );
-- 
-- CREATE TABLE IF NOT EXISTS permission_model_specifc_allows (
-- 	command TEXT NOT NULL,
-- 	is_allowed BOOLEAN DEFAULT false,
-- 	user_id INTEGER,
-- 	guild_id INTEGER REFERENCES guild_settings(guild_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE,
-- 	FOREIGN KEY (user_id, guild_id) REFERENCES member_settings (user_id, guild_id)
-- 		ON DELETE CASCADE ON UPDATE CASCADE,
-- 	PRIMARY KEY (guild_id, user_id, command)
-- );


-- END REGION