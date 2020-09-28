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

import asyncio
import os
import uuid
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional

import msgpack

from .utils import MainThreadSingletonMeta


class _ConfigBase:
    def __init__(self, fpname: str):
        self._path = Path(fpname)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._cached_data: Dict[Any, List[Any]] = {}
        self._load()

    @property
    def data(self) -> Mapping[str, Any]:
        return MappingProxyType(self._cached_data)

    def _load(self):
        """
        This should only get called once,
        and should be prior to connection with discord
        """
        if self._path.exists():
            with self._path.open(mode="rb") as read_buffer:
                self._cached_data = msgpack.load(read_buffer, strict_map_key=False)

    async def _save(self):
        async with self._lock:
            asyncio.get_running_loop().run_in_executor(
                None, _save_pack, self._path, self._cached_data
            )


class BasicConfig(_ConfigBase, metaclass=MainThreadSingletonMeta):
    """
    Can store some things that don't need to be handled by the DB

    This really shouldn't be a separate class (data itself) but until
    OSes have good async fileIO support, this remains useful
    """

    _cached_data: Dict[str, List[int]]

    def __init__(self):
        super().__init__("salamander.configpack")
        self._cached_data.setdefault("blocked_users", [])
        self._cached_data.setdefault("blocked_guilds", [])

    def user_is_blocked(self, user_id: int) -> bool:
        return user_id in self._cached_data["blocked_users"]

    def guild_is_blocked(self, guild_id: int) -> bool:
        return guild_id in self._cached_data["blocked_guilds"]

    async def block_user(self, user_id: int):
        blocked = self._cached_data["blocked_users"]
        if user_id not in blocked:
            blocked.append(user_id)
            await self._save()

    async def block_guild(self, guild_id: int):
        blocked = self._cached_data["blocked_guilds"]
        if guild_id not in blocked:
            blocked.append(guild_id)
            await self._save()

    async def unblock_user(self, user_id: int):
        blocked = self._cached_data["blocked_users"]
        try:
            blocked.remove(user_id)
        except ValueError:
            return
        else:
            await self._save()

    async def unblock_guild(self, guild_id: int):
        blocked = self._cached_data["blocked_guilds"]
        try:
            blocked.remove(guild_id)
        except ValueError:
            return
        else:
            await self._save()


class Prefixes(_ConfigBase, metaclass=MainThreadSingletonMeta):

    _cached_data: Dict[int, List[str]]

    def __init__(self):
        super().__init__("prefixes.configpack")

    async def add_prefix_for_guild(self, guild_id: int, prefix: str):
        guild_prefixes = self._cached_data.setdefault(guild_id, [])
        if prefix not in guild_prefixes:
            if len(guild_prefixes) >= 5:
                raise OverflowError("May only have 5 prefixes")
            guild_prefixes.append(prefix)
            guild_prefixes.sort(reverse=True)
            await self._save()

    async def reset_prefixes_for_guild(self, guild_id: int):
        if self._cached_data.pop(guild_id, None) is not None:
            await self._save()

    async def remove_prefix_for_guild(self, guild_id: int, prefix: str):
        guild_prefixes = self._cached_data.setdefault(guild_id, [])
        try:
            guild_prefixes.remove(prefix)
        except ValueError:
            return
        else:
            await self._save()


def _save_pack(path: Path, data: Dict[str, Any]) -> None:
    """
    Directory fsync is needed with temp file atomic writes
    https://lwn.net/Articles/457667/
    http://man7.org/linux/man-pages/man2/open.2.html#NOTES (synchronous I/O section)
    """
    filename = path.stem
    tmp_file = "{}-{}.tmp".format(filename, uuid.uuid4().fields[0])
    tmp_path = path.parent / tmp_file
    with tmp_path.open(mode="wb") as file_:
        file_.write(msgpack.packb(data))
        file_.flush()
        os.fsync(file_.fileno())

    tmp_path.replace(path)
    parent_directory_fd: Optional[int] = None
    try:
        parent_directory_fd = os.open(path.parent, os.O_DIRECTORY)
        if parent_directory_fd:
            os.fsync(parent_directory_fd)
    finally:
        if parent_directory_fd:
            os.close(parent_directory_fd)
