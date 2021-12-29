from dataclasses import dataclass
import socket
from typing import Dict, Tuple, List

import requests
from jsonrpcclient import request
from pyngrok import ngrok

from gimelnet.misc import logging
from gimelnet.misc.utils import Addr, recv_timeout


class Connection(dataclass):

    lpub: Addr
    lpriv: Addr
    rpub: Addr
    rpriv: Addr
    socket_instance: socket

    def speak(self, msg):
        pass

    def send(self, timeout=None):
        pass


# return graph
def pool_rpc(rpc) -> List[Addr]:
    response = requests.post(rpc, json=request("endpoints.get")).json()

    if response:
        return response['result']

    raise Exception()


def notify_rpc(rpc, addr):
    params = request('endpoints.add', {'addr': addr})
    response = requests.post(rpc, json=params)

    if response:
        return True

    raise Exception()


def in_network(addr):
    pass


def pack_message(msg) -> bytes:
    pass


DEFAULT_BIND_PORT = 6666
LOCALHOST = ('127.0.0.1', DEFAULT_BIND_PORT)

log = logging.getLogger(__name__)


class ConnectionsDispatcher:

    def __init__(self, rpc):
        self.rpc = rpc

        # as server
        self.listener = self._build_socket()
        self.listener.bind(LOCALHOST)

        tunnel = ngrok.connect(DEFAULT_BIND_PORT, 'tcp')
        tun_host, tun_port = tunnel.public_url.replace('tcp://', '').split(':')
        tun_port = int(tun_port)

        tunneled_addr = (tun_host, tun_port)

        log.info(f'Tunneled listener address: {tunneled_addr}')

        notify_rpc(rpc, tunneled_addr)

        # as client
        self.speaker = self._build_socket()

        log.info(f'Speaker address: {tunneled_addr}')

        self.endpoints = pool_rpc(rpc)

        self.connections_pool: Dict[Tuple[str, int], socket.socket] = dict()

    @staticmethod
    def _build_socket():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock

    def accept(self, timeout=None):
        listen_socket, listen_address = self.listener.accept()

        if not in_network(listen_address):
            # bad
            return

        self.connections_pool[listen_address] = listen_socket

    # noinspection PyMethodMayBeStatic
    def _recv(self, sock) -> str:
        return recv_timeout(sock)

    # noinspection PyMethodMayBeStatic
    def _send(self, sock, msg) -> bool:
        return sock.sendall(msg)

    def receive(self, readable) -> str:

        readable_socket = self.connections_pool.get(readable, None)

        if not readable_socket:
            raise Exception()

        received = self._recv(readable_socket)

        return received

    def response(self, writeable, response) -> bool:

        writeable_socket = self.connections_pool.get(writeable)

        if not writeable_socket:
            raise Exception()

        return self._send(writeable_socket, response)

    def update_pool(self, new_pool):
        pass










if __name__ == '__main__':
    my_private = ('12.24.42.23', 60)
    rpc_p = 'https://sdfdsf.com'

    connections_dispatcher = ConnectionsDispatcher(rpc_p)




