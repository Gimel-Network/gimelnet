import datetime
import os.path
import pathlib
import subprocess
import sys
import socket
from typing import Dict, Tuple, List

import requests
from jsonrpcclient import request, parse, Ok

from gimelnet.misc import logging
from gimelnet.misc.utils import Addr


# return graph
def pool_rpc(rpc) -> List[Addr]:
    response = requests.post(rpc, json=request("endpoints.get")).json()

    if response:
        ls = response['result'].split('\n')
        endpoints = []

        for u in ls:
            h, p = u.split(':')
            p = int(p)
            endpoints.append(Addr(h, p))

        return endpoints

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


def get_available_tunnel(rpc) -> Tuple[Addr, Addr]:

    # TODO (qnbhd) check connection
    iterations = 5

    for i in range(iterations):
        response = requests.post(rpc, json=request('tunnels.get'))
        parsed = parse(response.json())

        if isinstance(parsed, Ok):
            result = parsed.result
            slaver_h, slaver_p = parsed.result['slaver'].split(':')
            public_h, public_p = parsed.result['public'].split(':')
            return Addr.from_pair(slaver_h, slaver_p), Addr.from_pair(public_h, public_p)

    raise Exception('No available tunnels')


def in_network(addr):
    return True


def pack_message(msg) -> bytes:
    pass


DEFAULT_BIND_HOST = '127.0.0.1'
DEFAULT_BIND_PORT = 0

LOCALHOST = (DEFAULT_BIND_HOST, DEFAULT_BIND_PORT)
HOME = ('0.0.0.0', 0)

log = logging.getLogger(__name__)


def run_tunneling(port, master_addr: Addr):
    project_folder = pathlib.Path(__file__).parent.parent.parent
    slaver_path = os.path.join(project_folder, 'shootback', 'slaver.py')

    logs_folder = pathlib.Path('logs')
    logs_folder.mkdir(exist_ok=True)
    log_filename = f"node-run-{datetime.datetime.now().strftime('%m-%d-%Y-%h-%m-%s')}"

    out_file = os.path.join(logs_folder, f"{log_filename}-out.log")
    err_file = os.path.join(logs_folder, f"{log_filename}-errors.log")

    with open(out_file, "w", encoding='utf-8') as out, \
            open(err_file, "w", encoding='utf-8') as err:

        proc = subprocess.Popen([
            sys.executable, slaver_path,
            '-t', f'{DEFAULT_BIND_HOST}:{port}',
            '-m', f'{master_addr.host}:{master_addr.port}',
        ], stderr=err, stdout=out)

    return proc


class Connection:

    def __init__(self, sock=None):
        self.sock: socket.socket = sock or self._build_socket()
        self.listen_des = self.sock.makefile('r')
        self.write_des = self.sock.makefile('w')

    def accept(self):
        conn, addr = self.sock.accept()
        return Connection(conn), addr

    def connect(self, addr):
        self.sock.connect(addr)

    def send(self, msg: str):
        self.write_des.write(f'{msg}\n')
        self.write_des.flush()

    def read(self):
        return self.listen_des.readline().strip()

    def bind(self, addr):
        self.sock.bind(addr)

    def listen(self):
        self.sock.listen()

    def getsockname(self):
        return self.sock.getsockname()

    def getpeername(self):
        return self.sock.getpeername()

    def fileno(self):
        return self.sock.fileno()

    @staticmethod
    def _build_socket() -> socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock

    def close(self):
        self.listen_des.close()
        self.write_des.close()
        self.sock.close()

    def __repr__(self):
        raddr = None
        try:
            raddr = self.getpeername()
        except Exception as e:
            print(type(e), e)

        raddr = '' if raddr is None else f', raddr={raddr}'
        return f'Connection(laddr={self.sock.getsockname()}{raddr})'

    def __str__(self):
        return repr(self)


class ConnectionsDispatcher:

    def __init__(self, rpc):
        self.rpc = rpc

        # as server
        self.listener = Connection()
        self.listener.bind(LOCALHOST)
        self.listener.listen()

        slaver_addr, public_addr = get_available_tunnel(rpc)

        run_tunneling(self.listener.getsockname()[1], slaver_addr)

        self.tunneled_addr = slaver_addr
        self.public_addr = public_addr

        # log.info(f'Tunneled slaver address: {self.tunneled_addr}')
        log.info(f'Public customer addr: {self.public_addr}')
        notify_rpc(rpc, self.public_addr)

        self.endpoints = pool_rpc(rpc)

        self.connections_pool: Dict[Addr, Connection] = dict()

    def accept(self, timeout=None):
        listen_socket, listen_address = self.listener.accept()

        if not in_network(listen_address):
            # bad
            return

        self.connections_pool[Addr.from_pair(*listen_address)] = listen_socket

        return listen_socket, listen_address

    def connect(self, addr: Addr, timeout=None):
        if addr == self.public_addr:
            return
        if addr in self.connections_pool:
            return

        try:
            resp_socket = Connection()
            resp_socket.connect(addr)
            self.connections_pool[addr] = resp_socket
            log.info(f'Connection with {addr} was completed.')
            return True
        except ConnectionRefusedError:
            log.warning(f'Connection with {addr} was refused.')
            return False

    # noinspection PyMethodMayBeStatic
    def _recv(self, sock: Connection) -> str:
        return sock.read()

    # noinspection PyMethodMayBeStatic
    def _send(self, sock: Connection, msg: str):
        return sock.send(msg)

    def receive(self, readable: Addr) -> str:

        readable_socket = self.connections_pool.get(readable, None)

        if not readable_socket:
            raise Exception()

        received = self._recv(readable_socket)

        return received

    def request(self, writeable: Addr, response):

        writeable_socket = self.connections_pool.get(writeable)

        if not writeable_socket:
            raise Exception()

        self._send(writeable_socket, response)

    def update_pool(self):
        self.endpoints = pool_rpc(self.rpc)





