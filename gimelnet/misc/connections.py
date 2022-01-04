import os.path
import pathlib
import subprocess
import sys
import threading
from dataclasses import dataclass
import socket
from time import sleep
from typing import Dict, Tuple, List

import requests
from jsonrpcclient import request, parse, Ok
from pyngrok import ngrok

from gimelnet.misc import logging
from gimelnet.misc.utils import Addr, recv_timeout, get_ip
from shootback import slaver

# class Connection(dataclass):
#
#     lpub: Addr
#     lpriv: Addr
#     rpub: Addr
#     rpriv: Addr
#     socket_instance: socket
#
#     def speak(self, msg):
#         pass
#
#     def send(self, timeout=None):
#         pass


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
    response = requests.post(rpc, json=request('tunnels.get'))
    parsed = parse(response.json())

    if isinstance(parsed, Ok):
        result = parsed.result
        print(result, type(result))
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

log = logging.getLogger(__name__)


def run_tunneling(port, master_addr: Addr):

    # thread = threading.Thread(target=slaver.main,
    #                           args=(master_addr, Addr.from_pair(DEFAULT_BIND_HOST, port)),
    #                           daemon=True)
    #
    # thread.start()

    project_folder = pathlib.Path(__file__).parent.parent.parent
    slaver_path = os.path.join(project_folder, 'shootback', 'slaver.py')

    proc = subprocess.Popen([
        sys.executable, slaver_path,
        '-t', f'{DEFAULT_BIND_HOST}:{port}',
        '-m', f'{master_addr.host}:{master_addr.port}',
    ], stderr=sys.stdout, stdout=sys.stderr)

    return proc
    # try:
    #     outs, errs = proc.communicate(timeout=4)
    #     print(outs, errs)
    # except subprocess.TimeoutExpired:
    #     log.warning('Was close tunneling')
    #     proc.kill()
    #     outs, errs = proc.communicate()


    # tunnel = ngrok.connect(port, 'tcp')
    # tun_host, tun_port = tunnel.public_url.replace('tcp://', '').split(':')
    # return tun_host, int(tun_port)


class ConnectionsDispatcher:

    def __init__(self, rpc):
        self.rpc = rpc

        # as server
        self.listener = self._build_socket()
        self.listener.bind(LOCALHOST)
        self.listener.listen()
        print(self.listener.getsockname())

        slaver_addr, public_addr = get_available_tunnel(rpc)

        run_tunneling(self.listener.getsockname()[1], slaver_addr)

        self.tunneled_addr = slaver_addr
        self.public_addr = public_addr

        log.info(f'Tunneled slaver address: {self.tunneled_addr}')
        log.info(f'Public customer addr: {self.public_addr}')
        notify_rpc(rpc, self.public_addr)

        self.endpoints = pool_rpc(rpc)

        print(self.endpoints)

        self.connections_pool: Dict[Addr, socket.socket] = dict()

    @staticmethod
    def _build_socket():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock

    def accept(self, timeout=None):
        listen_socket, listen_address = self.listener.accept()

        print(listen_socket, listen_address)
        if not in_network(listen_address):
            # bad
            return

        self.connections_pool[Addr.from_pair(*listen_address)] = listen_socket

        return listen_socket, listen_address

    def connect(self, addr: Addr, timeout=None):
        if addr == self.public_addr:
            return

        try:
            resp_socket = self._build_socket()
            resp_socket.connect(addr)
            self.connections_pool[addr] = resp_socket
            log.info(f'Connection with {addr} was completed.')
            return True
        except ConnectionRefusedError:
            log.warning(f'Connection with {addr} was refused.')
            return False

    # noinspection PyMethodMayBeStatic
    def _recv(self, sock: socket.socket) -> str:
        return recv_timeout(sock)

    # noinspection PyMethodMayBeStatic
    def _send(self, sock: socket.socket, msg: str):
        return sock.sendall(msg.encode('utf-8'))

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





