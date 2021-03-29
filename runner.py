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
    no_basilisk = raw_data.pop("no_basilisk", False)

    ext_dict = raw_data.pop("exts", None)
    about_text = raw_data.pop("about_text", None)

    if ext_dict:
        exts = tuple(
            (
                *(f"src.extensions.{name}" for name in ext_dict.pop("core", ())),
                *(f"src.contrib_extensions.{name}" for name in ext_dict.pop("contrib", ())),
                *(f"src.local_extensions.{name}" for name in ext_dict.pop("local", ())),
                *ext_dict.pop("global", ()),
            )
        )
    else:
        exts = ()

    return BehaviorFlags(
        no_serpent=no_serpent,
        no_basilisk=no_basilisk,
        initial_exts=exts,
        about_text=about_text,
    )


def main():

    if TOKEN := os.environ.get("SALAMANDER_TOKEN", None):
        Salamander.run_with_wrapping(TOKEN, config=get_conf())
    else:
        sys.exit("No token?")


def timing_runner():

    import yappi
    import uuid

    yappi.set_clock_type("WALL")

    with yappi.run():
        if TOKEN := os.environ.get("SALAMANDER_TOKEN", None):
            Salamander.run_with_wrapping(TOKEN, config=get_conf())
        else:
            sys.exit("No token?")

    uid = uuid.uuid4()

    stats = yappi.get_func_stats()
    stats.save(f"salamander-{uid.hex}.callgrind", type="callgrind")
    stats.sae(f"salamander-{uid.hex}.pstat", type="pstat")


if __name__ == "__main__":
    main()
