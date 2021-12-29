import errno
import json
import traceback
from functools import cmp_to_key

from gimelnet.misc import logging

import time
from contextlib import suppress
import socket
from typing import NamedTuple, Generator
from jsonrpcclient import parse, request
import requests
from pyngrok import ngrok

from gimelnet.core.scheduler import Scheduler
from gimelnet.misc.connections import ConnectionsDispatcher
from gimelnet.misc.shared import SharedFactory, SharedList, SharedDict
from gimelnet.misc.utils import Addr, get_ip, send, jrpc, peer2key, key2peer, recv_timeout, is_port_open

log = logging.getLogger(__name__)

CHUNK_SIZE = 4096
DEFAULT_BIND_PORT = 6666


class p2p(NamedTuple):
    host: str
    port: int


class PeerProxy:

    def __init__(self, a2s, shared_factory: SharedFactory):
        self.a2s = a2s
        self.shared_factory = shared_factory

    def get_socket(self, host, port):
        serialized = peer2key(host, port)
        return self.a2s[serialized]

    def get_address(self, host, port):
        serialized = peer2key(host, port)
        return self.shared_factory['connected_peers', serialized]

    def add_socket(self, host, port, socket_):
        serialized = peer2key(host, port)
        self.a2s[serialized] = socket_

    def add_serialized(self, host, port, address):
        serialized = peer2key(host, port)
        self.shared_factory['connected_peers', serialized] = address


def interrogate_endpoint(endpoint_url):
    js = request("endpoint.get")

    response = requests.post(endpoint_url, json=js)

    if response:
        json_response = response.json()
        if 'error' not in json_response:
            print(json_response)
            hp = json_response['result'].rsplit(':', maxsplit=1)
            addr = Addr.from_pair(*hp)
            return addr

    return Addr.from_pair(get_ip(), DEFAULT_BIND_PORT)


CONNECTED_AS_PEER = 1
CONNECTED_AS_BINDER = 2


def connect_or_bind(addr: Addr):
    def build_socket():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock

    # firstly we try connect to addr
    ngrok.disconnect(addr.host)

    s = build_socket()
    try:
        s.settimeout(2)
        s.connect(addr)
        if recv_timeout(s):
            raise ConnectionRefusedError()
        s.settimeout(None)
        return s, CONNECTED_AS_PEER
    except (ConnectionRefusedError, socket.timeout, socket.gaierror):
        pass

    s = build_socket()
    s.bind(('localhost', DEFAULT_BIND_PORT))

    return s, CONNECTED_AS_BINDER


class Peer:

    def __init__(self, gimel_addr, rpc: str):
        # unique node address in p2p network

        self.gimel_addr = gimel_addr

        # host+port to socket
        # self.a2s = dict()

        self.scheduler = Scheduler()
        # self.scheduler.add_finalizer(self.finalizer)
        self.scheduler.add_exceptor(StopIteration, lambda e: print('Stop Iteration'))
        self.scheduler.add_exceptor(ConnectionResetError,
                                    lambda e: print('Connection reset error'))

        self.shared_factory = SharedFactory()

        # self.shared_factory.push('payload', SharedList(['1', '2']))
        # self.shared_factory.push('connected_peers', SharedDict())

        # self.scheduler.spawn_periodic(self.check_connected, 3)3
        # self.scheduler.spawn_periodic(self.shared_factory.share, 5)

        # self.peer_proxy = PeerProxy(self.a2s, self.shared_factory)

        # Is this node a super node?
        # Super node - one that currently
        # acts as a coordinator in the current p2p network
        self.connections_dispatcher = ConnectionsDispatcher(rpc)

        for endpoint in self.connections_dispatcher.endpoints:
            if self.connections_dispatcher.connect(endpoint):
                job = self.request_job(endpoint)
                self.scheduler.spawn(job)
        # self.is_super = True
        #
        # self.socket, code = connect_or_bind(self.netaddr)
        #
        # if code == CONNECTED_AS_BINDER:
        #     self.socket.listen()
        #
        #     log.info('Connect as server node.')
        #
        #     # here the logic is as follows: we will ask our rpc about
        #     # which host (super-node) is relevant at the moment, then
        #     # we will try to make bind for this address, if it does not
        #     # work, then we will try to connect to it. We assume that
        #     # RPC always gives us reliable information.
        #
        #     tunnel = ngrok.connect(DEFAULT_BIND_PORT, 'tcp')
        #
        #     tunnel_host, tunnel_port = tunnel.public_url.replace('tcp://', '').split(':')
        #     tunnel_port = int(tunnel_port)
        #
        #     request_params = (tunnel_host, tunnel_port)
        #     response = requests.post(endpoint, json=request("endpoint.set", request_params))
        #     log.debug(response.json())
        #
        #     log.info('Public tunnel URL: %s', tunnel.public_url)
        #
        #     self_serialized = peer2key(*request_params)
        #     self.shared_factory['connected_peers', self_serialized] = self.gimel_addr
        #
        #     acceptor = self.accept_connections()
        #     self.scheduler.spawn(acceptor)
        # else:
        #     self.is_super = False
        #     _, sp = self.socket.getsockname()
        #
        #     di = jrpc('peer.connect',
        #               host=get_ip(), port=sp,
        #               gimel_addr=self.gimel_addr)
        #
        #     dumped = json.dumps(di)
        #
        #     send(self.socket, dumped)
        #
        #     super_server = self.serve_super_node(self.socket)
        #     self.scheduler.spawn(super_server)
        #
        #     log.info('Connect as peer node.')
        #
        #     # noinspection PyProtectedMember
        #     self.scheduler._add_readable(self.socket, self.netaddr.to_pair())
        #
        # log.debug(f'Current node addr: {self.socket.getsockname()}')

    def accept_connections(self) -> Generator:
        """Accept new connections to current network. The blocking accept
        call is awaiting a new connection. As soon as a new connection
        occurs, we add a new socket, and we also create a new task to
        serve this node (generator). But this is not enough. By convention,
        the first message comes method = peer.connect, we extract the peer
        address from there and supplement the available information
        """

        while True:
            yield Scheduler.READ, self.connections_dispatcher.listener

            client_socket, address = self.connections_dispatcher.accept()

            log.info(f'Connection from {address}')
            # self.peer_proxy.add_socket(address[0], address[1], client_socket)

            job = self.response_job(client_socket)
            self.scheduler.spawn(job)

    # noinspection PyMethodMayBeStatic
    def response_job(self, target_addr: Addr):
        """A separate job for servicing a separate network node.
        Is a generator and triggers new messages from this node

        :param target_addr: client socket for servicing
        :return:
        """

        target_socket = self.connections_dispatcher.connections_pool[target_addr]

        while True:
            # return the control flow to the main loop
            yield Scheduler.READ, target_socket

            # followed by a blocking call-reading of data by timeout
            response = recv_timeout(target_socket)

            log.info(f'Receive message from {target_socket}: ')
            log.info(response)

            # socket connection broken sign
            if not response:
                target_socket.close()
                return

            # we assume that there may be errors in the transfer
            # of data,but we will simply skip this message if we
            # cannot do anything based on it
            # with suppress(json.JSONDecodeError):
            #     js = json.loads(response)
            #     log.info(json.dumps(js, indent=4))

            yield Scheduler.WRITE, target_socket

    def request_job(self, target_addr: Addr):

        target_socket = self.connections_dispatcher.connections_pool[target_addr]

        while True:
            yield Scheduler.READ, target_socket

            self.connections_dispatcher.request(target_addr, 'ping')

            log.debug('Sleep...')
            time.sleep(5)

            yield Scheduler.WRITE, target_socket

    def run(self):
        self.scheduler.run()

