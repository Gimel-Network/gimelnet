import json
import zlib
from contextlib import suppress
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


class SharedObjectExistsError(Exception):
    """Raises if shared object is exists in current shared pool"""


class SharedFactory:

    def __init__(self):
        self.shared_pool: Dict[str, _Shared] = dict()
        self.recipients: List[socket] = list()

    def push(self, identifier: str, sh: T):
        if identifier not in self.shared_pool:
            self.shared_pool[identifier] = _Shared(sh)
        else:
            raise SharedObjectExistsError(f'The {identifier} is exists'
                                          f' in current shared pool.')

    def update(self, identifier: str, new_obj: T):
        if identifier in self.shared_pool:
            self.shared_pool[identifier].update(new_obj)
        else:
            self.push(identifier, new_obj)

    def add_recipient(self, recipient_socket: socket):
        self.recipients.append(recipient_socket)

    def remove_recipient(self, recipient_socket: socket):
        self.recipients.remove(recipient_socket)

    def loads(self, fetched_data: dict):
        log.debug(f'Fetch data {fetched_data}')
        for identifier, new_obj in fetched_data.items():
            self.update(identifier, new_obj)

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
            with suppress(OSError):
                send(recipient, dumped)
            log.debug(f'Share objects from factory with with {recipient}')

    def share_one(self, identifier: str):
        if not self.recipients:
            return

        di = {identifier: self.shared_pool[identifier].value()}
        di = jrpc('shared.share', **di)
        dumped = json.dumps(di)

        for recipient in self.recipients:
            with suppress(OSError):
                send(recipient, dumped)
            log.debug(f'Share object {identifier} with {recipient}')
