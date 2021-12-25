import abc
import json
import os

from jsonrpcserver import Error, Success


class Storage(metaclass=abc.ABCMeta):

    def __init__(self):
        pass

    @abc.abstractmethod
    def __getitem__(self, item):
        raise NotImplementedError()

    @abc.abstractmethod
    def __setitem__(self, key, value):
        raise NotImplementedError()


class TestStorage(Storage):

    def __init__(self):
        super().__init__()
        self.storage = dict()

    def __getitem__(self, item):
        value = self.storage.get(item)
        value = Success(value) if value else Error(code='404', message=f'The {item} not founded.')
        return value

    def __setitem__(self, key, value):
        self.storage[key] = value


class JsonFileStorage(Storage):

    def __init__(self, filename=".storage.txt"):
        super().__init__()

        self.filename = filename

        if os.path.isfile(self.filename):
            return

        with open(self.filename, 'w') as js_storage:
            js_storage.write(json.dumps({}, indent=2))

    def _load_content(self) -> dict:
        with open(self.filename) as js_storage:
            content = js_storage.read()
            return json.loads(content)

    def __getitem__(self, item):
        data = self._load_content()
        return data.get(item, None)

    def __setitem__(self, key, value):
        data = self._load_content()

        data[key] = value

        with open(self.filename, 'w') as js_storage:
            js_storage.write(json.dumps(data, indent=2))
