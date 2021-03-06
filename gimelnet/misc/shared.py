import json
from contextlib import suppress
from socket import socket
from typing import TypeVar, List, Dict, Mapping

from gimelnet.misc import logging
from gimelnet.misc.connections import Connection
from gimelnet.misc.utils import send, jrpc


log = logging.getLogger(__name__)


class SharedObjectExistsError(Exception):
    """Raises if shared object is exists in current shared pool"""


class SharedObjectNotAvailableType(Exception):
    """Raises if shared object is exists in current shared pool"""


class SharedObject:

    __obj_type__ = type(None)

    def init(self, __obj=None, **kwargs):
        # noinspection PyAttributeOutsideInit
        self._inner = __obj or self.__obj_type__()

    def __new__(cls, __obj=None, **kwargs):
        cls_obj_type = cls.__dict__.get("__obj_type__")

        assert cls_obj_type is not None
        __obj = __obj or cls_obj_type()

        assert isinstance(__obj, cls_obj_type), \
            f'Expected {cls.__obj_type__}, received {__obj}'

        instance = object.__new__(cls)
        instance.init(__obj, **kwargs)

        return instance

    def __getitem__(self, item):
        self._inner.__getitem__(item)

    def _update(self, __m: Mapping):
        raise NotImplementedError()

    def _get(self, *keys):
        raise NotImplementedError()

    def _set(self, *keys, value):
        raise NotImplementedError()


class SharedDict(SharedObject):

    __obj_type__ = dict

    def _update(self, __m: Mapping):
        assert isinstance(__m, self.__obj_type__)
        self._inner.update(__m)

    def __str__(self):
        return f'SharedDict({json.dumps(self._inner, indent=4)[1:-1]})'

    def __repr__(self):
        return str(self)

    def keys(self):
        return self._inner.keys()

    def _set(self, *keys, value):
        if not keys:
            return self._inner

        rkey = keys[-1]

        result = self._inner

        for key in keys[:-1]:
            result = result[key]

        result[rkey] = value

    def _get(self, *keys):
        if not keys:
            return self._inner

        rkey = keys[-1]

        result = self._inner

        for key in keys[:-1]:
            result = result[key]

        return result[rkey]

    def _delete(self, *keys):
        if not keys:
            return self._inner

        rkey = keys[-1]

        result = self._inner

        for key in keys[:-1]:
            result = result[key]

        del result[rkey]


class SharedList(SharedObject):

    __obj_type__ = list

    def _update(self, __l: List):
        assert isinstance(__l, self.__obj_type__)
        self._inner[:] = __l

    def __str__(self):
        return f'SharedList({json.dumps(self._inner, indent=4)})'

    def __repr__(self):
        return str(self)

    def _set(self, *keys, value):
        if not keys:
            return self._inner

        rkey = keys[-1]

        result = self._inner

        for key in keys[:-1]:
            result = result[key]

        result[rkey] = value

    def _get(self, *keys):
        if not keys:
            return self._inner

        rkey = keys[-1]

        result = self._inner

        for key in keys[:-1]:
            result = result[key]

        return result[rkey]

    def _delete(self, *keys):
        if not keys:
            return self._inner

        rkey = keys[-1]

        result = self._inner

        for key in keys[:-1]:
            result = result[key]

        del result[rkey]


_Available = (SharedList, SharedDict)
T = TypeVar('T', SharedList, SharedDict)


class SharedFactory:

    def __init__(self):
        self.shared_pool: Dict[str, T] = dict()
        self.recipients: List[Connection] = list()

    def push(self, identifier: str, sh: T):
        if not isinstance(sh, _Available):
            raise SharedObjectNotAvailableType(f'Expected {_Available}, received {type(sh)}')

        if identifier not in self.shared_pool:
            self.shared_pool[identifier] = sh
        else:
            raise SharedObjectExistsError(f'The {identifier} is exists'
                                          f' in current shared factory.')

    def update(self, identifier: str, new_obj: T = None):
        if identifier not in self.shared_pool:
            raise SharedObjectExistsError(f'The shared object with'
                                          f' identifier {identifier}'
                                          f' was exists in currect shared factory.')

        # noinspection PyProtectedMember
        self.shared_pool[identifier]._update(new_obj)

    def delete(self, identifier, *keys):
        # noinspection PyProtectedMember
        self.shared_pool[identifier]._delete(keys)

    def add_recipient(self, recipient: Connection):
        self.recipients.append(recipient)

    def remove_recipient(self, recipient: Connection):
        self.recipients.remove(recipient)

    def loads(self, fetched_data: dict):
        log.debug(f'Fetch data {json.dumps(fetched_data, indent=4)}')
        for identifier, new_obj in fetched_data.items():
            self.update(identifier, new_obj)

    def set(self, identifier, *keys, value):
        # noinspection PyProtectedMember
        self.shared_pool[identifier]._set(*keys, value=value)

    def get(self, identifier, *keys):
        # noinspection PyProtectedMember
        return self.shared_pool[identifier]._get(*keys)

    def __getitem__(self, key):
        is_tuple = isinstance(key, tuple)
        identifier = key[0] if is_tuple else key
        keys = key[1:] if is_tuple else []
        self.get(identifier, *keys)

    def __setitem__(self, key, value):
        is_tuple = isinstance(key, tuple)
        identifier = key[0] if is_tuple else key
        keys = key[1:] if is_tuple else []
        self.set(identifier, *keys, value=value)

    def share(self):
        if not self.recipients:
            return

        # take identifiers, values of shared objects
        # and zip them
        ids = self.shared_pool.keys()

        # noinspection PyProtectedMember
        values = map(lambda v: v._inner, self.shared_pool.values())
        full_obj = zip(ids, values)

        # make correct request for our protocol
        di = jrpc('shared.share', **dict(full_obj))

        try:
            dumped = json.dumps(di)

            for recipient in self.recipients:
                with suppress(OSError):
                    recipient.send(dumped)
                    log.debug(f'Share objects from factory with with {recipient}')
        except (json.JSONDecodeError, TypeError):
            pass

    def share_one(self, identifier: str):
        if not self.recipients:
            return

        # noinspection PyProtectedMember
        di = {identifier: self.shared_pool[identifier]._inner}
        di = jrpc('shared.share', **di)
        dumped = json.dumps(di)

        for recipient in self.recipients:
            with suppress(OSError):
                recipient.send(dumped)
            log.debug(f'Share object {identifier} with {recipient}')
