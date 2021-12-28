import logging
import socket
import time
import zlib
from contextlib import suppress, closing
from typing import NamedTuple

import requests

CHUNK_SIZE = 4096
DEFAULT_BIND_PORT = 6666


def peer2key(host, port):
    """Get dict-like key for current host+port

    :type host: str
    :type port: str|int

    :rtype: str
    """
    port = int(port)
    return f"{host}+{port}"


def key2peer(serialized):
    """Extract host+port from key

    :type serialized: str
    :return: str,int

    """
    host, port = serialized.split('+')
    port = int(port)
    return host, port


def jrpc(method, *pos_params, **kw_params):
    assert bool(pos_params) ^ bool(kw_params), 'parameters can be positional or named'

    params = pos_params or kw_params

    di = {
        "jsonrpc": 2.0,
        "method": method,
        "params": params
    }

    return di


def send(the_socket: socket.socket, message: str):
    enc = message.encode('utf-8')
    compressed = zlib.compress(enc)
    the_socket.sendall(compressed)


def recv_timeout(the_socket, timeout=0.01):
    the_socket.setblocking(0)
    total_data = bytearray()

    begin = time.time()
    while True:
        if total_data and time.time() - begin > timeout:
            break
        elif time.time() - begin > timeout * 2:
            break

        # noinspection PyBroadException
        try:
            data = the_socket.recv(CHUNK_SIZE)
            if data:
                total_data += data
                begin = time.time()
            else:
                time.sleep(0.1)
        except BaseException:
            pass

    with suppress(zlib.error):
        total_data = zlib.decompress(total_data)

    decoded = total_data.decode('utf-8')

    return decoded


def get_ip():
    return requests.get('https://api.ipify.org').content.decode('utf8')


def is_port_open(host, port):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        return sock.connect_ex((host, port))


class Addr(NamedTuple):
    host: str
    port: int

    @classmethod
    def from_pair(cls, host, port):
        return cls(host, int(port))

    def to_pair(self):
        return self.host, self.port