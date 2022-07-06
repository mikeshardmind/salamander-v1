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

import contextlib
import logging
import os
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

import hyperscan
import msgpack
import zmq

log = logging.getLogger("basilisk")

MULTICAST_SUBSCRIBE_ADDR = os.environ.get("MULTICAST_SUBSCRIBE_ADDR", "tcp://127.0.0.1:5555")
PULL_REMOTE_ADDR = os.environ.get("PULL_REMOTE_ADDR", "tcp://127.0.0.1:5556")

MATCH_FOUND_TOPIC = "basilisk.gaze"
LOOK_FOR_MATCH = "basilisk.offer"
REFOCUS = "basilisk.refocus"
STATUS_CHECK = "status.check"
STATUS_RESPONSE = "status.response"
BASILISK = "basilisk"
INVALIDATE_CACHE = b"\x92\xb0cache.invalidate\xa8basilisk"  # msgpack.packb(("cache.invalidate", "basilisk"))


if base := os.getenv("DATA_DIR", None):
    base_path = Path(base)
else:
    base_path = Path()

SERIALIZED_PATH = base_path / "hs.db"
EXPRESSIONS_PATH = base_path / "patterns.list"

__version__ = "0.4.0a"


def only_once(f):
    has_called = False

    def wrapped(*args, **kwargs):
        nonlocal has_called

        if not has_called:
            has_called = True
            f(*args, **kwargs)

    return wrapped


def atomic_save(path: Path, data: bytes) -> None:
    """
    Directory fsync is needed with temp file atomic writes
    https://lwn.net/Articles/457667/
    http://man7.org/linux/man-pages/man2/open.2.html#NOTES (synchronous I/O section)
    """
    filename = path.stem
    tmp_file = "{}-{}.tmp".format(filename, uuid.uuid4().fields[0])
    tmp_path = path.parent / tmp_file
    with tmp_path.open(mode="wb") as file_:
        file_.write(data)
        file_.flush()
        os.fsync(file_.fileno())

    tmp_path.replace(path)
    parent_directory_fd: int | None = None
    try:
        parent_directory_fd = os.open(path.parent, os.O_DIRECTORY)
        if parent_directory_fd:
            os.fsync(parent_directory_fd)
    finally:
        if parent_directory_fd:
            os.close(parent_directory_fd)


def match_handler(pattern_id, start, end, flags, context):
    socket, rts = context
    payload = msgpack.packb((MATCH_FOUND_TOPIC, rts))
    socket.send(payload)


def check_match(db, rts, to_check, socket):
    if not db:
        logging.info("No DB, skipping scanning: %s", to_check)
    else:
        logging.info("Scanning: %s", to_check)
        db.scan(
            to_check,
            match_event_handler=only_once(match_handler),
            context=(socket, rts),
        )


def get_starting_db_exprs() -> tuple[hyperscan.Database | None, set[str]]:

    if SERIALIZED_PATH.exists() and EXPRESSIONS_PATH.exists():
        with contextlib.suppress(Exception):
            with SERIALIZED_PATH.open(mode="rb") as fp_r:
                db = hyperscan.loadb(fp_r.read())
            with EXPRESSIONS_PATH.open(mode="r") as fp:
                expressions = {e.strip() for e in fp.readlines() if e}

            return db, expressions

    if EXPRESSIONS_PATH.exists():
        with EXPRESSIONS_PATH.open(mode="r") as fp:
            expressions = {e.strip() for e in fp.readlines() if e}

        if expressions:

            try:
                db = hyperscan.Database()
                db.compile(expressions=tuple(expr.encode() for expr in expressions))
            except Exception as exc:
                log.exception("Error loading in expressions from file", exc_info=exc)
            else:
                return db, expressions

        else:

            return None, expressions

    return None, set()


def update_db_from_expressions(db: hyperscan.Database | None, expressions: set[str]) -> hyperscan.Database | None:
    log.info("Updating expressions to %s", expressions)
    if expressions:
        if not db:
            db = hyperscan.Database()

        db.compile(expressions=tuple(expr.encode() for expr in expressions))
        atomic_save(SERIALIZED_PATH, hyperscan.dumpb(db))
    else:
        db = None

    atomic_save(EXPRESSIONS_PATH, "\n".join(expressions).encode())

    return db


def main():

    raw_topics = (
        b"\x92\xaebasilisk.offer",
        b"\x92\xb0basilisk.refocus",
        b"\x92\xacstatus.check",
    )

    ctx = zmq.Context()
    sub_socket = ctx.socket(zmq.SUB)
    push_socket = ctx.socket(zmq.PUSH)
    for raw_topic in raw_topics:
        sub_socket.setsockopt(zmq.SUBSCRIBE, raw_topic)
    sub_socket.connect(MULTICAST_SUBSCRIBE_ADDR)
    push_socket.connect(PULL_REMOTE_ADDR)

    db, expressions = get_starting_db_exprs()
    log.info("expressions: %s", expressions)

    up_at = int(time.time())

    while True:
        try:
            msg = sub_socket.recv()

            topic, inner = msgpack.unpackb(msg, use_list=False, strict_map_key=False)

            if topic == LOOK_FOR_MATCH:
                check_match(db, *inner, push_socket)
            elif topic == REFOCUS:
                add, remove = inner
                expressions.update(add)
                expressions.difference_update(remove)
                db = update_db_from_expressions(db, expressions)
                push_socket.send(INVALIDATE_CACHE)
            elif topic == STATUS_CHECK:
                payload = msgpack.packb(
                    (
                        STATUS_RESPONSE,
                        (inner, BASILISK, up_at, {"patterns": tuple(expressions)}),
                    )
                )
                push_socket.send(payload)

        except Exception as exc:
            log.exception("Error when scanning from payload %s", msg, exc_info=exc)


if __name__ == "__main__":

    if not os.getenv("NOLOG", False):
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            style="%",
        )
        rotating_file_handler = RotatingFileHandler(base_path / "basilisk.log", maxBytes=10000000, backupCount=5)
        rotating_file_handler.setFormatter(formatter)
        log.addHandler(rotating_file_handler)
    if __debug__:
        log.setLevel(logging.INFO)
    else:
        log.setLevel(logging.WARNING)
    main()
