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

import asyncio
import contextlib

import apsw
import discord

from .utils import MainThreadSingletonMeta as Singleton

MAX_BALANCE = 2**63 - 1


class BalanceIssue(Exception):
    """Raised when an operation would cause a balance to go negative or exceed the maximum"""


def _get_balance(conn: apsw.Connection, guild_id: int, user_id: int) -> int:
    with contextlib.closing(conn.cursor()) as cursor:
        row = cursor.execute(
            """
            SELECT balance FROM accounts WHERE guild_id =? AND user_id = ?
            """,
            (guild_id, user_id),
        ).fetchone()
        return 0 if row is None else row[0]


def _deposit_saturating(conn: apsw.Connection, guild_id: int, user_id: int, value: int):

    v = int(value)
    if v < 1:
        raise ValueError("Must provide a positive, non negative integer value to deposit")

    if v > MAX_BALANCE:
        raise ValueError("Deposited value cannot be larger than the maximum allowed balance")

    with contextlib.closing(conn.cursor()) as cursor:
        cursor.execute(
            """
            INSERT INTO accounts (guild_id, user_id, balance)
            VALUES (?,?,?)
            ON CONFLICT (guild_id, user_id)
            DO UPDATE SET
                balance = min(9223372036854775807, balance + excluded.balance)
            """,
            (guild_id, user_id, value),
        )


def _deposit(conn: apsw.Connection, guild_id: int, user_id: int, value: int):

    v = int(value)
    if v < 1:
        raise ValueError("Must provide a positive, non negative integer value to deposit")

    if v > MAX_BALANCE:
        raise ValueError("Deposited value cannot be larger than the maximum allowed balance")

    with contextlib.closing(conn.cursor()) as cursor:
        # NB: change transfer below if this is changed
        cursor.execute(
            """
            INSERT INTO accounts (guild_id, user_id, balance)
            VALUES (?,?,?)
            ON CONFLICT (guild_id, user_id)
            DO UPDATE SET
                balance = balance + excluded.balance
            """,
            (guild_id, user_id, value),
        )


def _withdraw(conn: apsw.Connection, guild_id: int, user_id: int, value: int):
    v = int(value)
    if v < 1:
        raise ValueError("Must provide a positive, non negative integer value to withdraw")

    if v > MAX_BALANCE:
        raise ValueError("Deposited value cannot be larger than the maximum allowed balance")

    with contextlib.closing(conn.cursor()) as cursor:
        # This is a "clever" way to ensure the account already exists and won't go negative in a single statement
        # Keeping in mind that we expect setting an initial negative balance to fail with the check constraint
        # NB: change transfer below if this is changed
        cursor.execute(
            """
            INSERT INTO accounts (guild_id, user_id, balance)
            VALUES (?,?, 0 - ?)
            ON CONFLICT (guild_id, user_id)
            DO UPDATE SET
                balance = balance - excluded.balance
            """,
            (guild_id, user_id, value),
        )


def _transfer(conn: apsw.Connection, guild_id: int, sender_id: int, recipient_id: int, value):

    v = int(value)
    if v < 1:
        raise ValueError("Must provide a positive, non negative integer value to transfer")

    if v > MAX_BALANCE:
        raise ValueError("transfered value cannot be larger than the maximum allowed balance")

    with conn:
        with contextlib.closing(conn.cursor()) as cursor:
            # This is a combination of the non-saturating deposit and withdraw methods
            # wrapped in a savepoint
            # see apsw.Connection.__enter__ and https://sqlite.org/lang_savepoint.html for implementation specifics
            # see above comment about withdraw logic and change this when either withdraw or deposit are changed.
            cursor.execute(
                """
                INSERT INTO accounts (guild_id, user_id, balance)
                VALUES (:guild_id, :recv_id, :value)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET
                    balance = balance + excluded.balance;

                INSERT INTO accounts (guild_id, user_id, balance)
                VALUES (:guild_id, :send_id, :value)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET
                    balance = balance - excluded.balance;
                """,
                dict(
                    guild_id=guild_id,
                    recv_id=recipient_id,
                    send_id=sender_id,
                    value=value,
                ),
            )


class Bank(metaclass=Singleton):
    """
    Exists to cordinate economy commands.
    No economy commands are considered core,
    and this is only to prevent conflicts and provide a reasonable API
    """

    def __init__(self, connection: apsw.Connection):
        self._conn: apsw.Connection = connection
        with contextlib.closing(self._conn.cursor()) as cursor:
            cursor.execute(""" PRAGMA foreign_keys=ON """)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    balance INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id),
                    CHECK (balance >= 0 AND balance <= 9223372036854775807)
                )
                """
            )

    async def deposit_saturating(self, guild_id: int, user_id: int, value: int):
        """
        Deposit an amount, capping the user's balance rather than erroring if it would exceed the maximum
        """
        await asyncio.to_thread(_deposit_saturating, self._conn, guild_id, user_id, value)

    async def deposit(self, guild_id: int, user_id: int, value: int):
        try:
            await asyncio.to_thread(_deposit, self._conn, guild_id, user_id, value)
        except apsw.ConstraintError:
            raise BalanceIssue("This would exceed the maximum account balance.")

    async def withdraw(self, guild_id: int, user_id: int, value: int):
        try:
            await asyncio.to_thread(_withdraw, self._conn, guild_id, user_id, value)
        except apsw.ConstraintError:
            raise BalanceIssue("Insufficient balance.")

    async def transfer(self, guild_id: int, sender_id: int, recipient_id: int, value: int):
        try:
            await asyncio.to_thread(_transfer, self._conn, guild_id, sender_id, recipient_id, value)
        except apsw.ConstraintError:
            # We don't attempt to detect which case here.
            raise BalanceIssue(
                "This would either cause the sender to go negative or the recipient to overflow their account"
            )

    async def get_balance(self, guild_id: int, user_id: int) -> int:
        return await asyncio.to_thread(_get_balance, guild_id, user_id)
