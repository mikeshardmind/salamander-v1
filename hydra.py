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


"""
This exists so that we have a stable point of communication and socket ownership
for components that are less robust, such as those which might fail abruptly
due to external API issues. There's little room to improve this design wise
unless the design of the whole application needs adjustments for scale.
"""

import os

import zmq


def main(pub_addr: str, pull_addr: str):
    ctx = zmq.Context()
    puller = ctx.socket(zmq.PULL)
    publisher = ctx.socket(zmq.PUB)

    publisher.bind(pub_addr)
    puller.bind(pull_addr)

    while True:
        msg = puller.recv()
        publisher.send(msg)


def debug_main(pub_addr: str, pull_addr: str):
    """Duplicated code to avoid runtime costs when not debugging. Must be kept in sync with above."""

    import logging
    import sys

    log = logging.getLogger("hydra")
    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        style="%",
    )

    handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(formatter)

    log.debug("Started")
    log.debug("Binding to %s for incoming messages", pull_addr)
    log.debug("Binding to %s for outgoing messages", pub_addr)

    # Begin duplicated code from func:``main``

    ctx = zmq.Context()
    puller = ctx.socket(zmq.PULL)
    publisher = ctx.socket(zmq.PUB)

    publisher.bind(pub_addr)
    puller.bind(pull_addr)

    while True:
        msg = puller.recv()
        publisher.send(msg)

        # Duplicated code ends here

        log.debug("Forwared message: %s", msg)


if __name__ == "__main__":

    pub_addr = os.getenv("PUSH_ADDR", "tcp://127.0.0.1:5555")
    pull_addr = os.getenv("PULL_ADDR", "tcp://127.0.0.1:5556")

    if os.getenv("HYDRA_DEBUG", False):
        debug_main(pub_addr, pull_addr)
    else:
        main(pub_addr, pull_addr)
