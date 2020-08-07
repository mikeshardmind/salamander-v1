from __future__ import annotations

"""
Module for handling the IPC abstractions

We'll want a central ZMQ publisher to handle the binds used here,
Discord's API won't be as stable as our internals,
so we'll prefer binds in other portions of the architecture.
"""
import asyncio
from itertools import islice

import msgpack  # TODO: consider protobuf or blosc instead
import zmq
import zmq.asyncio


def chunked(it, size):
    it = iter(it)
    return iter(lambda: tuple(islice(it, size)), ())


def serializer(msg):
    # Can change chunk size later
    return chunked(msgpack.packb(msg), 4000)


class ZMQHandler:
    def __init__(self):
        self.ctx = zmq.asyncio.Context()
        # This can't be unbounded or we will have backpressure issues
        # 50 message backlog is probably too many, but we'll tune this later.
        self.recieved_queue = asyncio.Queue(maxsize=50)
        # This however can
        self.push_queue = asyncio.Queue()
        self.sub_socket = self.ctx.socket(zmq.SUB)
        self.push_socket = self.ctx.socket(zmq.PUSH)
        self.sub_socket.connect("tcp://localhost:5555")
        for topic in ("salamander", "broadcast", "cache", "filter"):
            self.sub_socket.setsockopt(zmq.SUBSCRIBE, topic)
        self.push_socket.connect("tcp://localhost:5556")

    async def push(self, msg):
        return await self.push_queue.put(msg)

    async def get(self):
        return await self.recieved_queue.get()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        ...

    def start(self):
        ...

    async def run_zmq(self):
        ...

    async def subscriber_task(self):
        while True:
            topic, message = await self.sub_socket.recv_multipart()
            await self

    async def push_task(self):

        while True:
            msg = await self.push_queue.get()
            await self.push_socket.send_serialized(msg, serializer, copy=False)
            self.push_queue.task_done()
