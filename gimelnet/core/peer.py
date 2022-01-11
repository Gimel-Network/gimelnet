from gimelnet.misc import logging

import time
from typing import Generator

from gimelnet.core.scheduler import Scheduler
from gimelnet.misc.connections import ConnectionsDispatcher
from gimelnet.misc.shared import SharedFactory, SharedList
from gimelnet.misc.utils import Addr

log = logging.getLogger(__name__)


class Peer:

    def __init__(self, rpc: str):

        self.scheduler = Scheduler()
        self.scheduler.add_exceptor(StopIteration, lambda e: print('Stop Iteration'))
        self.scheduler.add_exceptor(ConnectionResetError,
                                    lambda e: print('Connection reset error'))

        self.shared_factory = SharedFactory()
        self.shared_factory.push('test', SharedList(['1', '2']))
        self.scheduler.spawn_periodic(self.shared_factory.share, 5)

        self.connections_dispatcher = ConnectionsDispatcher(rpc)
        self.scheduler.spawn(self.accept_connections())

        self.connect_to_endpoints()

    def connect_to_endpoints(self):
        self.connections_dispatcher.update_pool()
        for endpoint in self.connections_dispatcher.endpoints:
            if connection := self.connections_dispatcher.connect(endpoint):
                log.info(f'Try connect to {endpoint}')
                job = self.request_job(endpoint)
                self.shared_factory.add_recipient(connection)
                self.scheduler.spawn(job)

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
            connection, address = self.connections_dispatcher.accept()

            log.info(f'Connection from {address}')
            # self.peer_proxy.add_socket(address[0], address[1], client_socket
            self.connect_to_endpoints()

            self.shared_factory.add_recipient(connection)
            job = self.response_job(address)
            self.scheduler.spawn(job)

    # noinspection PyMethodMayBeStatic
    def response_job(self, target_addr: Addr):
        """A separate job for servicing a separate network node.
        Is a generator and triggers new messages from this node

        :param target_addr: client socket for servicing
        :return:
        """

        connection = self.connections_dispatcher.connections_pool[target_addr]

        while True:
            # return the control flow to the main loop
            yield Scheduler.READ, connection

            response = connection.read()

            log.info(f'Receive messages from {connection}: ')
            log.info(response)

            # socket connection broken sign
            if not response:
                connection.close()
                return

    def request_job(self, target_addr: Addr):

        connection = self.connections_dispatcher.connections_pool[target_addr]

        while True:
            yield Scheduler.WRITE, connection

            connection.send('ping')
            time.sleep(2)

    def run(self):
        self.scheduler.run()

