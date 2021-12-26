import socket
import time
from typing import NamedTuple

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


class PeerProxy:

    def __init__(self, a2a, a2s):
        self.a2a = a2a
        self.a2s = a2s

    def get_socket(self, host, port):
        address = self.get_address(host, port)
        return self.a2s[address]

    def get_address(self, host, port):
        serialized = peer2key(host, port)
        return self.a2a[serialized]

    def add_socket(self, host, port, socket_):
        serialized = peer2key(host, port)
        self.a2s[serialized] = socket_

    def add_serialized(self, host, port, address):
        serialized = peer2key(host, port)
        self.a2a[serialized] = address


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
    the_socket.sendall(enc)


def recv_timeout(the_socket, timeout=0.01):
    the_socket.setblocking(0)
    total_data = []

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
                total_data.append(data)
                begin = time.time()
            else:
                time.sleep(0.1)
        except BaseException:
            pass

    return ''.join([u.decode('utf-8') for u in total_data])


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ggl = ('8.8.8.8', 80)
    s.connect(ggl)
    ip, _ = s.getsockname()
    s.close()
    return ip


class Addr(NamedTuple):
    host: str
    port: int

    @classmethod
    def from_pair(cls, host, port):
        return cls(host, int(port))

    def to_pair(self):
        return self.host, self.port