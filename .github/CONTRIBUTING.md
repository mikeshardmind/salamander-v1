## This is a bit sparse right now and more detail will be added to this later. The following guidelines apply to contributions.


1. All contributions, code or otherwise, should follow the project code of conduct.
2. All code contributions from non-members should be discussed in advance. Please do not open a pull request without having done this.
3. Python source files should be formatted with [black](https://github.com/psf/black) and with [isort](https://github.com/PyCQA/isort), using the compatible profile.
4. Pull requests should have a limited scope to what they intend to accomplish.
5. Commit messages should be meaningful.


## The following guidelines apply to commands


### Use of discord.py's "consume rest"

1. Discord models should never use consume rest behavior.
2. Consume rest should only be used on text input that does not require a conversion, 
   and only if there is no preceeding argument which could reasonably be part of that text.
3. When reasonable, use ignore_extra=False in command constructors to handle user feedback related to this.

This ensures clear, consistent user facing behavior.


### How to determine which check to use for commands.

1. Commands which don't do anything which can be considered a mod/admin action are entirely discretionary
2. Commands which modify the bot globally should be owner only
3. Commands which configure the bot for a server should be admin or having manage server
4. Commands which take moderation actions should be mod or the permissions needed to take that action manually.

Additionally, commands which can configure the moderation network (see basalisk, et al) will require a different check in the future.


### Command groups

1. Command groups should not do anything on their own, a subcommand should be invoked.
2. Command groups should have the same check as the least restricted subcommand in the group.
3. Command groups invoked without a subcommand should send the help for that group.