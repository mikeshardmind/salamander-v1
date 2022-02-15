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

# Single file form of <https://github.com/mikeshardmind/rapid_dev_storage>
# Included here by original author under a different license.

import functools
import keyword
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Dict, List, Literal, Tuple, Union

import apsw
import msgpack

__all__ = [
    "NoValue",
    "SQLiteBackend",
    "Storage",
    "StorageBackend",
    "StorageGroup",
    "StoredValue",
]

AnyStorable = Union[Dict[str, Any], List[Any], int, float, str, None]


class _NoValueType:
    """
    Represents when there is no data.
    This is distinct from storing a value of None
    """

    def __bool__(self):
        return False


NoValue = _NoValueType()


class StorageBackend(ABC):
    """
    This abstract base class shows the interfaces
    required to use a class as a replacement backend for the included ones
    Interfaces here are async to allow dropping
    in other interfaces which would strictly need to be async
    """

    @abstractmethod
    async def write_data(self, group_name: str, *keys: str, value: AnyStorable):
        ...

    @abstractmethod
    async def get_data(self, group_name: str, *keys: str) -> Union[AnyStorable, _NoValueType]:
        ...

    @classmethod
    @abstractmethod
    async def create_backend_instance(
        cls,
        path: Path,
        name: str,
        unique_identifier: int,
        *,
        serializer=None,
        deserializer=None,
    ):
        ...

    @abstractmethod
    async def clear_by_keys(self, group_name: str, *keys: Union[str, int]):
        ...

    @abstractmethod
    async def clear_group(self, group_name: str):
        ...

    @abstractmethod
    async def clear_by_key_prefix(self, group_name: str, *keys: Union[str, int]):
        ...

    @abstractmethod
    def get_all_by_group(self, group_name: str) -> AsyncIterator[Tuple[Tuple[str, ...], AnyStorable]]:
        """Concrete implmentations must asynchronously yield a 2-tuple of (key tuple, value)"""
        ...

    @abstractmethod
    def get_all_by_key_prefix(
        self, group_name: str, *keys: Union[str, int]
    ) -> AsyncIterator[Tuple[Tuple[str, ...], AnyStorable]]:
        """Concrete implementations must asynchronously yield a 2-tuple of (key tuple, value)"""
        ...


class StoredValue:
    """
    Representation of everything needed to interact with a stored value, methods included
    """

    def __init__(self, backend: StorageBackend, group_name: str, *keys: str):
        self.backend: StorageBackend = backend
        self._keys: Tuple[str, ...] = keys
        self._group_name: str = group_name

    def set_value(self, value: AnyStorable) -> Awaitable[None]:
        """
        Sets a value
        """
        return self.backend.write_data(self._group_name, *self._keys, value=value)

    def get_value(self) -> Awaitable[Union[AnyStorable, _NoValueType]]:
        """
        Gets a value if it exists, otherwise returns ``NoValue``
        """
        return self.backend.get_data(self._group_name, *self._keys)

    def clear_value(self) -> Awaitable[None]:
        """Clears a value. This does not require that the value already existed"""
        return self.backend.clear_by_keys(self._group_name, *self._keys)


class StorageGroup:
    def __init__(self, backend: StorageBackend, group_name: str):
        self.backend = backend
        self._group_name = group_name

    def __getitem__(self, keys) -> StoredValue:

        # The key value restriction is an implementation detail of the included
        # SQLiteBackend class.
        # I suggest retaining it, but this can also be replaced.

        k_l = len(keys)
        if not 0 < k_l < 5:
            raise ValueError(f"Must provide between 1 and 5 keys, got {k_l}")
        if None in keys:
            raise TypeError(f"Keys must not be None")

        return StoredValue(self.backend, self._group_name, *keys)

    def clear_group(self) -> Awaitable[None]:
        """Clears an entire group"""
        return self.backend.clear_group(self._group_name)

    async def all_items(self) -> AsyncIterator[Tuple[Tuple[Union[str, int], ...], AnyStorable]]:
        """
        Iterates over all items stored in the group
        The data is yielded as a 2-tuple consisting of the tuple key,
        and the value which was associated
        """
        async for key, value in self.backend.get_all_by_group(self._group_name):
            yield key, value


class Storage:
    """
    This is the basic storage wrapper class.
    It can be extended with additional functionality
    and adapters for specific data types, as well as adding
    facotry methods for instantiation including the required backend
    """

    def __init__(self, backend: StorageBackend):
        self.backend: StorageBackend = backend

    def get_group(self, name: str) -> StorageGroup:
        return StorageGroup(self.backend, name)


class SQLiteBackend(StorageBackend):
    """
    This holds all the SQLite Logic.
    All lookups operate on a composite primary key,
    ensuring that the abstration has minimal runtime performance overhead.
    This does incur a small cost to the DB size, though this is acceptible.
    Interface is async despite the underlying code not being so.
    This is intentional, as if used as-is, without competeting on the same table
    with other applications, it should not block the event loop.
    Meanwhile, the interface being async consistently leaves room for drop in replacements
    which may actually utilize the async nature,
    or further features which might have the potential to be blocking
    There are a handful of computed SQL queries.
    These are limited against user input, and userinput is not allowed to be formatted in,
    with 1 exception of the table name.
    This name is restricted in nature as to be safe,
    and properly bracketed so that it is never seen as an SQL expression
    Changes to the computed queries should be done with caution to ensure this remains true.
    For additional peace of mind,
    you can choose to disallow user input from being used as part of the
    table_name at the application layer, which leaves all remaining potential user input
    inserted as parameters.
    """

    def __init__(self, connection, table_name: str, serializer, deserializer):
        self._connection = connection
        self._table_name = table_name
        self._serializer = serializer
        self._deserializer = deserializer

    async def clear_group(self, group_name: str):
        cursor = self._connection.cursor()

        cursor.execute(
            f""" DELETE FROM [ {self._table_name} ] WHERE group_name = ? """,
            (group_name,),
        )

    async def clear_by_key_prefix(self, group_name: str, *keys: Union[str, int]):
        cursor = self._connection.cursor()
        sqlite_args = (group_name,) + keys
        key_len = len(keys)

        # This doesn't insert any user provided values into the formatting and is safe
        # It's a mess, but this is the concession price for what's achieved here.

        match_partial = " AND ".join(f"k{i}=?" for i in range(1, key_len + 1))
        cursor.execute(
            f"""
            DELETE FROM [ {self._table_name} ]
                WHERE group_name=? AND {match_partial}
            """,
            sqlite_args,
        )

    async def clear_by_keys(self, group_name: str, *keys: Union[str, int]):

        cursor = self._connection.cursor()
        sqlite_args = (group_name,) + keys

        key_len = len(keys)

        # This doesn't insert any user provided values into the formatting and is safe
        # It's a mess, but this is the concession price for what's achieved here.

        match_partial = " AND ".join(f"k{i}=?" for i in range(1, key_len + 1))
        if key_len < 5:
            match_partial += " AND " + " AND ".join(f"k{i} IS NULL" for i in range(key_len + 1, 6))

        cursor.execute(
            f"""
            DELETE FROM [ {self._table_name} ]
                WHERE group_name=? AND {match_partial}
            """,
            sqlite_args,
        )

    async def write_data(self, group_name: str, *keys: str, value: Union[AnyStorable, _NoValueType]):
        v = self._serializer(value)
        sqlite_args = (group_name,) + keys + (5 - len(keys)) * (None,) + (v,)
        cursor = self._connection.cursor()

        cursor.execute(
            f"""
            INSERT OR REPLACE INTO [ {self._table_name} ]
            (group_name, k1, k2, k3, k4, k5, data)
            VALUES (?,?,?,?,?,?,?)
            """,
            sqlite_args,
        )

    async def get_data(self, group_name: str, *keys: str) -> Union[AnyStorable, _NoValueType]:

        cursor = self._connection.cursor()
        sqlite_args = (group_name,) + keys

        key_len = len(keys)

        # This doesn't insert any user provided values into the formatting and is safe
        # It's a mess, but this is the concession price for what's achieved here.

        match_partial = " AND ".join(f"k{i}=?" for i in range(1, key_len + 1))
        if key_len < 5:
            match_partial += " AND " + " AND ".join(f"k{i} IS NULL" for i in range(key_len + 1, 6))

        for (data,) in cursor.execute(
            f"""
            SELECT data FROM [ {self._table_name} ]
                WHERE group_name=? AND {match_partial}
            """,
            sqlite_args,
        ):
            return self._deserializer(data)
        return NoValue

    @classmethod
    async def create_backend_instance(
        cls,
        path: Union[Path, Literal[":memory:"]],
        name: str,
        unique_identifier: int,
        *,
        serializer=None,
        deserializer=None,
        existing_connection=None,
    ):

        if not (name.isidentifier() and not keyword.iskeyword(name)):
            raise ValueError(
                "value for parameter name must not be a python keyword and must be a valid python identifier"
            )

        table_name = f"_{name}-{unique_identifier}"

        con = existing_connection or apsw.Connection(str(path))

        cursor = con.cursor()

        cursor.execute(""" PRAGMA journal_mode="wal" """)

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS [ {table_name} ] (
                group_name TEXT NOT NULL,
                k1 TEXT,
                k2 TEXT,
                k3 TEXT,
                k4 TEXT,
                k5 TEXT,
                data BLOB,
                PRIMARY KEY (group_name, k1, k2, k3, k4, k5)
            );
            """
        )

        serializer = serializer or msgpack.packb
        deserializer = deserializer or functools.partial(msgpack.unpackb, use_list=False)

        return cls(con, table_name, serializer, deserializer)

    @classmethod
    def create_backend_instance_sync(
        cls,
        path: Union[Path, Literal[":memory:"]],
        name: str,
        unique_identifier: int,
        *,
        serializer=None,
        deserializer=None,
        existing_connection=None,
    ):

        if not (name.isidentifier() and not keyword.iskeyword(name)):
            raise ValueError(
                "value for parameter name must not be a python keyword " "and must be a valid python identifier"
            )

        table_name = f"_{name}-{unique_identifier}"

        con = existing_connection or apsw.Connection(str(path))

        cursor = con.cursor()

        cursor.execute(""" PRAGMA journal_mode="wal" """)

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS [ {table_name} ] (
                group_name TEXT NOT NULL,
                k1 TEXT,
                k2 TEXT,
                k3 TEXT,
                k4 TEXT,
                k5 TEXT,
                data BLOB,
                PRIMARY KEY (group_name, k1, k2, k3, k4, k5)
            );
            """
        )

        serializer = serializer or msgpack.packb
        deserializer = deserializer or functools.partial(msgpack.unpackb, use_list=False)

        return cls(con, table_name, serializer, deserializer)

    async def get_all_by_group(self, group_name: str):

        cursor = self._connection.cursor()

        for row in cursor.execute(
            f"""
            SELECT data, k1, k2, k3, k4, k5 FROM [ {self._table_name} ]
            WHERE group_name = ?
            """,
            (group_name,),
        ):
            raw_data, *raw_keys = row

            keys = tuple(k for k in raw_keys if k is not None)
            data = self._deserializer(raw_data)
            yield keys, data

    async def get_all_by_key_prefix(self, group_name: str, *keys: Union[str, int]):

        cursor = self._connection.cursor()
        sqlite_args = (group_name,) + keys

        key_len = len(keys)

        # This doesn't insert any user provided values into the formatting and is safe
        # It's a mess, but this is the concession price for what's achieved here.

        match_partial = " AND ".join(f"k{i}=?" for i in range(1, key_len + 1))

        for row in cursor.execute(
            f"""
            SELECT data, k1, k2, k3, k4, k5 FROM [ {self._table_name} ]
            WHERE group_name = ? AND {match_partial}
            """,
            sqlite_args,
        ):
            raw_data, *raw_keys = row

            keys = tuple(k for k in raw_keys if k is not None)
            data = self._deserializer(raw_data)
            yield keys, data
