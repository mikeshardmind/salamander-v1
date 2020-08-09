from __future__ import annotations

"""
Module for handling the IPC abstractions

We'll want a central ZMQ publisher to handle the binds used here,
Discord's API won't be as stable as our internals,
so we'll prefer binds in other portions of the architecture.
"""
import asyncio
from typing import Iterator, Sequence

import msgpack  # TODO: consider protobuf or blosc instead
import zmq
import zmq.asyncio

MULTICAST_SUBSCRIBE_ADDR = "epgm://localhost:5555"
PULL_REMOTE_ADDR = "tcp://localhost:5556"


def chunked(data: Sequence[bytes], size: int) -> Iterator[Sequence[bytes]]:
    return (data[i : i + size] for i in range(0, len(data), size))


def serializer(msg: Sequence[bytes]) -> Iterator[Sequence[bytes]]:
    # Can change chunk size later for performance tuning if needed, however
    # anything between 64b and 8kb is fine on the target system in
    # terms of sockets and minimizing blocking.
    return chunked(msgpack.packb(msg), 4000)


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
        self.sub_socket = self.ctx.socket(zmq.SUB)
        self.push_socket = self.ctx.socket(zmq.PUSH)
        self._push_task = None
        self._recv_task = None
        self._started = asyncio.Event()
        self.topics = ("salamander", "broadcast", "basalisk.gaze", "notice.cache")

    async def push(self, topic, msg):
        return await self.push_queue.put((topic, msg))

    async def get(self):
        return await self.recieved_queue.get()

    async def __aenter__(self):
        self.sub_socket.setsockopt(zmq.SUBSCRIBE, b"")
        self.sub_socket.connect(MULTICAST_SUBSCRIBE_ADDR)
        self.push_socket.connect(PULL_REMOTE_ADDR)

        self._push_task = asyncio.create_task(self.push_loop())
        self._recv_task = asyncio.create_task(self.recv_loop())

        return self

    async def __aexit__(self, *args):
        self.sub_socket.close()
        self.push_socket.close()
        self._push_task.cancel()
        self._recv_task.cancel()
        await asyncio.gather(self._push_task, self._recv_task, return_exceptions=True)

    async def recv_loop(self):
        while True:
            payload = await self.sub_socket.recv()
            topic, message = msgpack.unpackb(
                payload, strict_map_key=False, use_list=False
            )
            if topic in self.topics:
                await self.recieved_queue.put((topic, message))

    async def push_loop(self):
        while True:
            topic, msg = await self.push_queue.get()
            await self.push_socket.send(msgpack.packb((topic, msg)))
            self.push_queue.task_done()
