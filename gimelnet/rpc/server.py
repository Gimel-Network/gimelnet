import random
from itertools import chain

from oslash import Either
from sanic import Sanic
from sanic.request import Request
from sanic.response import json
from jsonrpcserver import Success, Error, dispatch_to_serializable, method
from jsonrpcserver.result import SuccessResult, ErrorResult

# jsonrpcserver patch for linter
from gimelnet.rpc.storage import JsonFileStorage

Result = Either[ErrorResult, SuccessResult]

app = Sanic("Gimelchain-testnet-endpoint")
storage = JsonFileStorage()
storage['endpoints'] = dict()
storage['tunnels'] = list()


@method(name='endpoints.get')
def endpoints_get() -> Result:
    if value := storage['endpoints']:
        print(value)
        return Success('\n'.join(value))
    return Error(code=404, message='Not found key.')


@method(name='endpoints.add')
def endpoints_add(host: str, port: int) -> Result:
    storage['endpoints'] = list(set(chain(storage['endpoints'], [f'{host}:{port}'])))
    return Success()


@method(name="tunnels.get")
def get_available_tunnel() -> Result:
    if len(storage['tunnels']):
        return Success(random.choice(storage['tunnels']))
    return Error(code=101, message='Not available tunnels')


@method(name="tunnels.add")
def add_tunnel(host, port) -> Result:
    storage['tunnels'] = list(set(chain(storage['tunnels'], [f'{host}:{port}'])))
    return Success()


@method(name="tunnels.del")
def del_tunnel(host, port) -> Result:
    if f'{host}:{port}' in storage['tunnels']:
        storage['tunnels'] = storage['tunnels'].remove(f'{host}:{port}')
        return Success()
    return Error(code=202, message='Not in tunnels storage.')


@app.route("/", methods=["POST"])
async def router(request: Request):
    middle = dispatch_to_serializable(request.body)
    return json(middle)


def main():
    app.run('0.0.0.0', port=5000)


if __name__ == "__main__":
    main()
