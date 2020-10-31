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

import os
import pathlib
import sys
from typing import Optional

import toml

from src.bot import BehaviorFlags, Salamander


def get_conf() -> Optional[BehaviorFlags]:

    path = pathlib.Path("config.toml")

    if not (path.exists() and path.is_file()):
        return None

    raw_data = toml.load(path)

    no_serpent = raw_data.pop("no_serpent", False)
    no_basalisk = raw_data.pop("no_basalisk", False)

    ext_dict = raw_data.pop("exts", None)

    if ext_dict:
        exts = tuple(
            (
                *(f"src.extensions.{name}" for name in ext_dict.pop("core", ())),
                *(
                    f"src.contrib_extensions.{name}"
                    for name in ext_dict.pop("contrib", ())
                ),
                *(f"src.local_extensions.{name}" for name in ext_dict.pop("local", ())),
                *ext_dict.pop("global", ()),
            )
        )
    else:
        exts = ()

    return BehaviorFlags(
        no_serpent=no_serpent, no_basalisk=no_basalisk, initial_exts=exts
    )


def main():
    if TOKEN := os.environ.get("SALAMANDER_TOKEN", None):
        Salamander.run_with_wrapping(TOKEN, config=get_conf())
    else:
        sys.exit("No token?")


if __name__ == "__main__":
    main()
