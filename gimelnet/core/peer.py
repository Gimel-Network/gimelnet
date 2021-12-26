import json

from gimelnet.misc import logging

import time
from contextlib import suppress
import socket
from typing import NamedTuple, Generator
from jsonrpcclient import parse, request
import requests

from gimelnet.core.scheduler import Scheduler
from gimelnet.misc.shared import SharedFactory
from gimelnet.misc.utils import Addr, get_ip, send, jrpc, peer2key, key2peer, recv_timeout

log = logging.getLogger(__name__)

CHUNK_SIZE = 4096
DEFAULT_BIND_PORT = 6666


class p2p(NamedTuple):
    host: str
    port: int


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


def interrogate_endpoint(endpoint_url):
    js = request("endpoint.get")

    response = requests.post(endpoint_url, json=js)

    if response:
        json_response = response.json()
        if 'error' not in json_response:
            print(json_response)
            hp = json_response['result'].split(':')
            addr = Addr.from_pair(*hp)
            return addr

    return Addr.from_pair(get_ip(), DEFAULT_BIND_PORT)


class Peer:

    def __init__(self, xorname, endpoint: str):
        # unique node address in p2p network

        self.xorname = xorname
        self.netaddr = interrogate_endpoint(endpoint)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # host+port to xorname
        self.a2a = dict()
        # host+port to socket
        self.a2s = dict()
        self.peer_proxy = PeerProxy(self.a2a, self.a2s)

        self.scheduler = Scheduler()
        self.scheduler.add_finalizer(self.finalizer)
        self.scheduler.add_exceptor(StopIteration, lambda e: print('Stop Iteration'))
        self.scheduler.add_exceptor(ConnectionResetError,
                                    lambda e: print('Connection reset error'))

        self.shared_factory = SharedFactory()

        payload = ['1', '2']
        self.shared_factory.push('payload', payload)
        self.shared_factory.push('connected_peers', self.a2a)

        self.scheduler.spawn_periodic(self.check_connected, 3)
        self.scheduler.spawn_periodic(self.shared_factory.share, 5)

        # Is this node a super node?
        # Super node - one that currently
        # acts as a coordinator in the current p2p network
        self.is_super = True

        try:
            self.socket.bind(self.netaddr)
            self.socket.listen()
            
            log.info('Connect as server node.')

            # here the logic is as follows: we will ask our rpc about
            # which host (super-node) is relevant at the moment, then
            # we will try to make bind for this address, if it does not
            # work, then we will try to connect to it. We assume that
            # RPC always gives us reliable information.

            request_params = [get_ip(), DEFAULT_BIND_PORT]
            response = requests.post(endpoint, json=request("endpoint.set", request_params))
            log.debug(response.json())

            acceptor = self.accept_connections()
            self.scheduler.spawn(acceptor)
        except OSError:
            self.socket.connect(self.netaddr)
            self.is_super = False
            sh, sp = self.socket.getsockname()

            di = jrpc('peer.connect',
                      host=sh, port=sp,
                      xorname=self.xorname)

            dumped = json.dumps(di)

            send(self.socket, dumped)

            super_server = self.serve_super_node(self.socket)
            self.scheduler.spawn(super_server)

            log.info('Connect as peer node.')

            # noinspection PyProtectedMember
            self.scheduler._add_readable(self.socket, self.netaddr.to_pair())

        self_serialized = peer2key(*self.netaddr)
        self.a2a[self_serialized] = self.xorname

        log.debug(f'Current node addr: {self.socket.getsockname()}')

    def finalizer(self):
        if self.is_super:
            return

        host, port = self.socket.getsockname()
        di = jrpc('peer.disconnect',
                  host=host, port=port)

        send(self.socket, json.dumps(di))

    # noinspection DuplicatedCode
    def on_super_node_destroy(self, host, port):
        """What should happen when the super-node leaves the current network."""

        self.scheduler.clear()

        self.socket.close()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))
        self.socket.listen()

        acceptor = self.accept_connections()
        self.scheduler.spawn(acceptor)

    def accept_connections(self) -> Generator:
        """Accept new connections to current network. The blocking accept
        call is awaiting a new connection. As soon as a new connection
        occurs, we add a new socket, and we also create a new task to
        serve this node (generator). But this is not enough. By convention,
        the first message comes method = peer.connect, we extract the peer
        address from there and supplement the available information
        """

        while True:

            yield Scheduler.READ, self.socket

            client_socket, address = self.socket.accept()

            log.info(f'Connection from {address}')
            self.peer_proxy.add_socket(address[0], address[1], client_socket)
            self.shared_factory.add_recipient(client_socket)

            job = self.serve_node(client_socket)
            self.scheduler.spawn(job)

    def on_peer_connect(self, method, host, port, xorname):
        """Add new peer to a2a-dict object and share with
        other peers in current network via shared_factory.
        """

        self.peer_proxy.add_serialized(host, port, xorname)
        self.shared_factory.share_one('connected_peers')

    def on_peer_disconnect(self, method, host, port):
        # Actual only for super-node
        serialized = peer2key(host, port)
        del self.a2a[serialized]
        del self.a2s[serialized]

    def check_connected(self):
        for sock in self.a2s.values():
            di = jrpc('ping', {})
            send(sock, json.dumps(di))

    def serve_node(self, client_socket):
        """A separate job for servicing a separate network node.
        Is a generator and triggers new messages from this node

        :param client_socket: client socket for servicing
        :return: None

        """

        while True:
            # return the control flow to the main loop
            yield Scheduler.READ, client_socket

            # followed by a blocking call-reading of data by timeout
            response = recv_timeout(client_socket)

            log.info(f'Receive message from {client_socket}: ')

            # socket connection broken sign
            if not response:
                client_socket.close()
                return

            # we assume that there may be errors in the transfer
            # of data,but we will simply skip this message if we
            # cannot do anything based on it
            with suppress(json.JSONDecodeError):
                js = json.loads(response)
                log.info(json.dumps(js, indent=4))

                # TODO (qnbhd) make registration callbacks mechanism
                if js['method'] == 'peer.connect':
                    self.on_peer_connect(js['method'], **js['params'])
                elif js['method'] == 'peer.disconnect':
                    self.on_peer_disconnect(js['method'], **js['params'])

            yield Scheduler.WRITE, client_socket

    def lifeguard(self):
        # TODO (qnbhd) make lifeguard search algorithm
        return min(key2peer(serialized)
                   for serialized in self.a2a.keys())

    def serve_super_node(self, server_socket):
        while True:
            yield Scheduler.READ, server_socket
            message = recv_timeout(server_socket)

            if not message:
                log.info('All peers are dead.')
                # noinspection PyProtectedMember
                self.scheduler._readable.clear()

                with suppress(KeyError):
                    key = peer2key(*self.netaddr)
                    del self.a2a[key]

                lg_host, lg_port = self.lifeguard()

                log.warning(f'Lifeguard name: ({lg_host}, {lg_port})')

                if self.socket.getsockname() == (lg_host, lg_port):
                    log.warning('My node is lifeguard. Try to take responsibilities.')
                    self.on_super_node_destroy(lg_host, lg_port)

                    acceptor = self.accept_connections()
                    self.scheduler.spawn(acceptor)

                    yield 'DELETE', None
                else:
                    i = 0
                    while i < 5 or server_socket.recv(4096):
                        log.warning(f'Trying connection to {self.netaddr}')
                        print(self.a2a)

                        params = [
                            {
                                'host': key2peer(serialized)[0],
                                'port': key2peer(serialized)[1],
                                'address': self.a2a[serialized]
                            }
                            for serialized, name in self.a2a.items()
                        ]

                        log.warning(json.dumps(params, indent=4))
                        time.sleep(2)
                        i += 1

                    # trying to create new connection
                    self.scheduler.clear()

                    self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    self.socket.connect((lg_host, lg_port))

                    super_server = self.serve_super_node(self.socket)
                    self.scheduler.spawn(super_server)

                    yield 'DELETE', None

            js = json.loads(message)
            log.debug(json.dumps(js, indent=4))

            if js['method'] == 'shared.share':
                params = js['params']
                self.shared_factory.loads(params)
                #
                # for u in params:
                #     self.peer_proxy.add_serialized(u['host'], u['port'], u['serialized'])

            # TODO (qnbhd) what about message send method?
            # recipient = random.choice(list(self.a2a.values()))
            # self.send_message(recipient, 'Hello bro')

            yield Scheduler.WRITE, server_socket

    def run(self):
        self.scheduler.run()

    def send_message(self, to, msg):
        transfer = dict(zip(self.a2a.values(), self.a2a.keys()))
        address = transfer[to]

        h, p = self.socket.getsockname()
        to_h, to_p = address.split('+')

        di = jrpc('message.send', **{
            "from": {
                "host": h,
                "port": p,
                "xorname": self.xorname
            },
            "to": {
                "host": to_h,
                "port": to_p,
                "xorname": to
            },
            "message": msg
        })

        send(self.a2s[address] if self.is_super else self.socket, json.dumps(di))

