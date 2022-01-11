import asyncio
import os
import socket
from typing import List

import aiojobs
import requests
from sanic import Sanic
from sanic.request import Request
from sanic.response import json
from jsonrpcserver import Success, Error, dispatch_to_serializable, method
from jsonrpcserver.result import SuccessResult, ErrorResult
from jsonrpcclient import request, parse, Ok
import aiohttp

from gimelnet.misc import logging
from gimelnet.misc.connections import get_available_tunnel, run_tunneling

log = logging.getLogger(__name__)


def pool_rpc(rpc) -> List[str]:
    response = requests.post(rpc, json=request("endpoints.get")).json()

    if response:
        parsed = parse(response)

        return parsed.result.split('\n')

    raise Exception()


def notify_rpc(rpc, addr):

    # TODO (qnbhd) check connection
    response = requests.post(rpc, json=request(
        'endpoints.add',
        params={
            'host': addr[0],
            'port': addr[1]
            }
    ))

    if response:
        return True

    raise Exception()


class SanicPeer:

    def __init__(self, rpc, uuid):
        self.uuid = uuid
        self.rpc = rpc
        self.app = Sanic('Gimel-node')
        self.endpoints = pool_rpc(rpc)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(('127.0.0.1', 6666))

        slaver_addr, public_addr = get_available_tunnel(self.rpc)
        run_tunneling(self.sock.getsockname()[1], slaver_addr)

        self.public_addr = public_addr

        log.info(f'Public address: {public_addr}')

        notify_rpc(rpc, self.public_addr)

        @method(name='hello')
        def hello():
            return Success(result='Hello too..')

    async def ping_others(self):
        for node in self.endpoints:
            async with aiohttp.ClientSession() as session:
                async with session.post(node, data=request('hello')) as resp:
                    hello = await resp.json()
                    log.info(f'Response from {node}: {parse(hello)}')

    def run(self):
        server_socket = '/tmp/sanic.sock'

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        try:
            os.remove(server_socket)
        finally:
            sock.bind(('127.0.0.1', 6666))

        srv_coro = self.app.create_server(
            sock=sock,
            return_asyncio_server=True,
            asyncio_server_kwargs=dict(
                start_serving=False
            )
        )

        async def runner():
            scheduler = await aiojobs.create_scheduler()
            scheduler.spawn(srv_coro)
            scheduler.spawn(self.ping_others)

            await scheduler.close()

        asyncio.get_event_loop().run_until_complete(runner())
