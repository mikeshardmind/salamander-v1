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

from ...bot import ExtensionManifest
from .cog import Feedback

extension_info = ExtensionManifest(
    required_bot_perms=18432,
    cog_names=["Feedback"],
    top_level_command_names=["feedback", "feedbackset"],
    url="https://github.com/unified-moderation-network/salamander",
    authors=["https://github.com/unified-moderation-network/"],
    license_info="https://github.com/unified-moderation-network/salamander/raw/main/LICENSE",
    data_retention_description="This extension does not store any user data. It does store feedback specifically provided to the bot.",
    remove_guild_data=ExtensionManifest.no_removal_handling_required,
    remove_user_data=ExtensionManifest.no_removal_handling_required,
)


def setup(bot):
    bot.add_cog(Feedback(bot))
