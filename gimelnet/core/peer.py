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
        address = self.get_address(host, port)
        return self.a2s[address]

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
    # ngrok.disconnect(addr.host)

    s = build_socket()
    try:
        s.settimeout(2)
        s.connect(addr)
        s.settimeout(None)
        return s, CONNECTED_AS_PEER
    except (ConnectionRefusedError, socket.timeout, socket.gaierror):
        pass

    s = build_socket()
    s.bind(('localhost', DEFAULT_BIND_PORT))

    return s, CONNECTED_AS_BINDER


class Peer:

    def __init__(self, gimel_addr, endpoint: str):
        # unique node address in p2p network

        self.gimel_addr = gimel_addr
        self.netaddr = interrogate_endpoint(endpoint)
        self.endpoint = endpoint

        # host+port to socket
        self.a2s = dict()

        self.scheduler = Scheduler()
        self.scheduler.add_finalizer(self.finalizer)
        self.scheduler.add_exceptor(StopIteration, lambda e: print('Stop Iteration'))
        self.scheduler.add_exceptor(ConnectionResetError,
                                    lambda e: print('Connection reset error'))

        self.shared_factory = SharedFactory()

        self.shared_factory.push('payload', SharedList(['1', '2']))
        self.shared_factory.push('connected_peers', SharedDict())

        self.scheduler.spawn_periodic(self.check_connected, 3)
        self.scheduler.spawn_periodic(self.shared_factory.share, 5)

        self.peer_proxy = PeerProxy(self.a2s, self.shared_factory)

        # Is this node a super node?
        # Super node - one that currently
        # acts as a coordinator in the current p2p network
        self.is_super = True

        self.socket, code = connect_or_bind(self.netaddr)

        if code == CONNECTED_AS_BINDER:
            self.socket.listen()

            log.info('Connect as server node.')

            # here the logic is as follows: we will ask our rpc about
            # which host (super-node) is relevant at the moment, then
            # we will try to make bind for this address, if it does not
            # work, then we will try to connect to it. We assume that
            # RPC always gives us reliable information.

            tunnel = ngrok.connect(DEFAULT_BIND_PORT, 'tcp')

            tunnel_host, tunnel_port = tunnel.public_url.replace('tcp://', '').split(':')
            tunnel_port = int(tunnel_port)

            request_params = (tunnel_host, tunnel_port)
            response = requests.post(endpoint, json=request("endpoint.set", request_params))
            log.debug(response.json())

            log.info('Public tunnel URL: %s', tunnel.public_url)

            self_serialized = peer2key(*request_params)
            self.shared_factory['connected_peers', self_serialized] = self.gimel_addr

            acceptor = self.accept_connections()
            self.scheduler.spawn(acceptor)
        else:
            self.is_super = False
            _, sp = self.socket.getsockname()

            di = jrpc('peer.connect',
                      host=get_ip(), port=sp,
                      gimel_addr=self.gimel_addr)

            dumped = json.dumps(di)

            send(self.socket, dumped)

            super_server = self.serve_super_node(self.socket)
            self.scheduler.spawn(super_server)

            log.info('Connect as peer node.')

            # noinspection PyProtectedMember
            self.scheduler._add_readable(self.socket, self.netaddr.to_pair())

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

        tunnel = ngrok.connect(addr=DEFAULT_BIND_PORT)
        log.info('Public tunnel URL: %s', tunnel.public_url)

        acceptor = self.accept_connections()
        self.scheduler.spawn(acceptor)

        request_params = (tunnel.public_url, DEFAULT_BIND_PORT)
        response = requests.post(self.endpoint, json=request("endpoint.set", request_params))

        if response:
            # TODO (qnbhd) add verifying for response
            pass

        log.warning(f'Change super-node to {request_params}')

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

    def on_peer_connect(self, method, host, port, gimel_addr):
        """Add new peer to a2a-dict object and share with
        other peers in current network via shared_factory.
        """

        # this call changes the a2a-dict
        self.peer_proxy.add_serialized(host, port, gimel_addr)
        # share connected peers with other nodes
        self.shared_factory.share_one('connected_peers')

    def check_connected(self):
        to_remove = dict()
        for serialized, sock in self.a2s.items():
            di = jrpc('ping', {})
            try:
                send(sock, json.dumps(di))
            except (OSError, ConnectionResetError):
                to_remove[serialized] = sock

        for serialized, sock in to_remove.items():
            log.warning(f'Remove recipient {serialized}')

            self.shared_factory.remove_recipient(sock)

            del self.a2s[serialized]

            self.shared_factory.delete('connected_peers', serialized)

    def serve_node(self, client_socket):
        """A separate job for servicing a separate network node.
        Is a generator and triggers new messages from this node

        :param client_socket: client socket for servicing
        :return:
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
                    # self.on_peer_disconnect(js['method'], **js['params'])

            yield Scheduler.WRITE, client_socket

    def lifeguard(self):
        # TODO (qnbhd): make lifeguard search algorithm
        def comparator(x, y):
            addr_x = key2peer(x)
            addr_y = key2peer(y)

            is_open_x = is_port_open(*addr_x)
            is_open_y = is_port_open(*addr_y)

            if is_open_x and is_open_y:
                return 1 if addr_x > addr_y else -1

            if not is_open_x and not is_open_y:
                raise Exception('No lifeguard peers available')

            return 1 if is_open_x else -1

        key = cmp_to_key(comparator)

        peers = self.shared_factory['connected_peers']

        log.warning(peers)

        return Addr(*min(peers.keys(), key=key))

    def on_super_node_disconnect(self, super_node_socket):
        # TODO (qnbhd): do we really have to
        #  immediately disconnect from all reading-jobs?
        # noinspection PyProtectedMember
        self.scheduler._readable.clear()

        with suppress(KeyError):
            key = peer2key(*self.netaddr)
            self.shared_factory.delete('connected_peers', key)

        log.warning('Super-node was disconnected, try reconnect'
                    ' with timeout 10sec.')

        try_receive = recv_timeout(super_node_socket, timeout=10)

        if try_receive:
            # the case when we managed to reconnect to the super-node
            pass

        lifeguard = self.lifeguard()
        log.warning(f'Lifeguard: {lifeguard}')

        if self.socket.getsockname() == lifeguard:
            # lifeguard node will try to take over the server's
            # responsibilities and establish a connection.
            # The rest of the nodes should connect to the
            # current lifeguard
            log.warning('My node is lifeguard. Try to take responsibilities.')

            self.on_super_node_destroy(('localhost', DEFAULT_BIND_PORT))

            # create new accept job
            acceptor = self.accept_connections()
            self.scheduler.spawn(acceptor)

            # remove current job from scheduler
            yield Scheduler.DELETE_JOB, None

        # branch only if we are not a lifeguard node,
        # and could not reconnect to the last super-node

        time.sleep(5)

        # trying to create new connection
        self.scheduler.clear()

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.connect(lifeguard)

        super_server = self.serve_super_node(self.socket)
        self.scheduler.spawn(super_server)

        yield Scheduler.DELETE_JOB, None

    def serve_super_node(self, server_socket):
        while True:
            print('Iter')
            yield Scheduler.READ, server_socket
            message = recv_timeout(server_socket)

            if not message:
                log.info('All peers are dead.')
                # noinspection PyProtectedMember
                yield self.on_super_node_disconnect(server_socket)

            js = json.loads(message)
            log.debug(json.dumps(js, indent=4))

            log.warning(self.shared_factory['connected_peers'])

            if js['method'] == 'shared.share':
                params = js['params']
                self.shared_factory.loads(params)

            # TODO (qnbhd) what about message send method?
            # recipient = random.choice(list(self.a2a.values()))
            # self.send_message(recipient, 'Hello bro')

            yield Scheduler.WRITE, server_socket

    def run(self):
        self.scheduler.run()

    # noinspection PyUnreachableCode
    def send_message(self, to, msg):

        raise Exception()

        transfer = dict(zip(self.a2a.values(), self.a2a.keys()))
        address = transfer[to]

        h, p = self.socket.getsockname()
        to_h, to_p = address.split('+')

        di = jrpc('message.send', **{
            "from": {
                "host": h,
                "port": p,
                "gimel_addr": self.gimel_addr
            },
            "to": {
                "host": to_h,
                "port": to_p,
                "gimel_addr": to
            },
            "message": msg
        })

        send(self.a2s[address] if self.is_super else self.socket, json.dumps(di))
