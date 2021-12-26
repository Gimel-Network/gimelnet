import json
from socket import socket
from typing import TypeVar, List, Dict

from gimelnet.misc import logging
from gimelnet.misc.utils import send, jrpc

T = TypeVar('T',
            int, float, str, bool,
            list, dict)


log = logging.getLogger(__name__)


class _Shared:

    def __init__(self, obj: T):
        self.object = obj
        self.recipients: List[socket] = []

    def update(self, new_obj: T):
        assert type(self.object) == type(new_obj)
        self.object = new_obj

    def value(self):
        return self.object

    def add_recipient(self, recipient_socket: socket):
        self.recipients.append(recipient_socket)


class SharedFactory:

    def __init__(self):
        self.shared_pool: Dict[str, _Shared] = dict()
        self.recipients: List[socket] = list()

    def push(self, identifier: str, sh: T):
        shared = _Shared(sh)
        self.shared_pool[identifier] = shared

    def update(self, identifier: str, new_obj: T):
        self.shared_pool[identifier].update(new_obj)

    def add_recipient(self, recipient_socket: socket):
        self.recipients.append(recipient_socket)

    def share(self):
        if not self.recipients:
            return

        # take identifiers, values of shared objects
        # and zip them
        ids = self.shared_pool.keys()
        values = map(lambda v: v.value(), self.shared_pool.values())
        full_obj = zip(ids, values)

        # make correct request for our protocol
        di = jrpc('shared.share', **dict(full_obj))
        dumped = json.dumps(di)

        for recipient in self.recipients:
            send(recipient, dumped)
            log.debug(f'Share objects from factory with with {recipient}')

    def share_one(self, identifier: str):
        if not self.recipients:
            return

        di = {identifier: self.shared_pool[identifier].value()}
        di = jrpc('shared.share', di)

        for recipient in self.recipients:
            send(recipient, di)
            log.debug(f'Share object {identifier} with {recipient}')
