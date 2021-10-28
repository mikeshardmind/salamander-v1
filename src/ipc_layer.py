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

"""
Module for handling the IPC abstractions

We'll want a central ZMQ publisher to handle the binds used here,
Discord's API won't be as stable as our internals,
so we'll prefer binds in other portions of the architecture.
"""
import asyncio
from contextvars import ContextVar

import msgpack
import zmq
import zmq.asyncio

MULTICAST_SUBSCRIBE_ADDR: ContextVar[str] = ContextVar("MULTICAST_SUBSCRIBE_ADDR", default="tcp://127.0.0.1:5555")
PULL_REMOTE_ADDR: ContextVar[str] = ContextVar("PULL_REMOTE_ADDR", default="tcp://127.0.0.1:5556")


class ZMQHandler:
    def __init__(self):
        self.ctx = zmq.asyncio.Context()
        # This could be entirely unbounded using zmq's highwater mark,
        # but moving this out of zmq partially allows the event loop
        # to play catchup in bursty situations, especially since we don't
        # always handle every event we listen for
        # (situational depending on discord state)
        self.recieved_queue = asyncio.Queue(maxsize=50)
        # This however can
        self.push_queue = asyncio.Queue()
        self.sub_socket = self.ctx.socket(zmq.SUB)  # pylint: disable=no-member
        self.push_socket = self.ctx.socket(zmq.PUSH)  # pylint: disable=no-member
        self._push_task = None
        self._recv_task = None
        # I can handle subscribing "properly" to these later
        # Example of subscribe topic isn't simple though
        # "salamander" => b"\x92\xaasalamander"
        # However, this only works as the first element of a 2-tuple
        # (3-tuple would be prefixed b"\x93\xae") and so on,
        # since msgpack can be streamed, it pre-informs of elements rather than
        # pairing start and end.
        # This can be considered more once the payloads are more set in stone.
        self.topics = (
            "salamander",
            "broadcast",
            "basilisk.gaze",
            "notice.cache",
            "status.response",
            "status.check",
        )

    def put(self, topic, msg):
        return self.push_queue.put_nowait((topic, msg))

    async def get(self):
        return await self.recieved_queue.get()

    async def __aenter__(self):
        self.sub_socket.setsockopt(zmq.SUBSCRIBE, b"")  # pylint: disable=no-member
        self.sub_socket.connect(MULTICAST_SUBSCRIBE_ADDR.get())
        self.push_socket.connect(PULL_REMOTE_ADDR.get())

        self._push_task = asyncio.create_task(self.push_loop())
        self._recv_task = asyncio.create_task(self.recv_loop())

        return self

    async def __aexit__(self, *args):
        self.sub_socket.close()
        self.push_socket.close()
        assert self._push_task is not None, "Typing memes"  # nosec
        assert self._recv_task is not None, "Typing memes"  # nosec
        self._push_task.cancel()
        self._recv_task.cancel()
        await asyncio.gather(self._push_task, self._recv_task, return_exceptions=True)

    async def recv_loop(self):
        while True:
            payload = await self.sub_socket.recv()
            topic, message = msgpack.unpackb(payload, strict_map_key=False, use_list=False)
            await self.recieved_queue.put((topic, message))

    async def push_loop(self):
        while True:
            topic, msg = await self.push_queue.get()
            await self.push_socket.send(msgpack.packb((topic, msg)))
            self.push_queue.task_done()
