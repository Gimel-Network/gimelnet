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


@method(name='endpoints.get')
def endpoints_get() -> Result:
    if value := storage['endpoints']:
        print(value)
        return Success('\n'.join(value))
    return Error(code=404, message='Not found key.')


@method(name='endpoints.add')
def endpoints_add(host: str, port: int) -> Result:
    storage['endpoints'] = list(set(chain(storage['endpoints'] or [], [f'{host}:{port}'])))
    return Success()


@app.route("tunnels.get", methods=["POST"])
async def get_available_tunnel():
    return random.choice(storage['tunnels'])


@app.route("tunnels.add", methods=["POST"])
async def add_tunnel(host, port):
    storage['tunnels'] = list(set(chain(storage['endpoints'] or [], [f'{host}:{port}'])))


@app.route("tunnels.del", methods=["POST"])
async def del_tunnel(host, port):
    if f'{host}:{port}' in storage['tunnels']:
        storage['tunnels'].remove(f'{host}:{port}')
        return Success()
    return Error(message='Not in tunnels storage.')


@app.route("/", methods=["POST"])
async def router(request: Request):
    middle = dispatch_to_serializable(request.body)
    return json(middle)


def main():
    app.run('0.0.0.0', port=5000)


if __name__ == "__main__":

    main()
