import datetime
import os
import random
import subprocess
import sys
from os.path import dirname, abspath
from time import sleep

from oslash import Either
from sanic import Sanic
from sanic.request import Request
from sanic.response import json
from jsonrpcserver import Success, Error, dispatch_to_serializable, method
from jsonrpcserver.result import SuccessResult, ErrorResult
from pathlib import Path

# jsonrpcserver patch for linter
from gimelnet.rpc.storage import JsonFileStorage

Result = Either[ErrorResult, SuccessResult]

app = Sanic("Gimelchain-testnet-endpoint")
storage = JsonFileStorage()
storage.set('endpoints', list())
storage.set('tunnels', list())
storage.set('slaver2public', dict())


@method(name='endpoints.get')
def endpoints_get() -> Result:
    value = storage.get('endpoints')
    print(value)
    return Success('\n'.join(value))


@method(name='endpoints.add')
def endpoints_add(host: str, port: int) -> Result:
    endpoints = storage.get('endpoints')
    endpoints.append(f'{host}:{port}')
    endpoints = set(endpoints)
    endpoints = list(endpoints)

    storage.set('endpoints', endpoints)
    return Success()


@method(name="tunnels.get")
def get_available_tunnel() -> Result:
    tunnels = storage.get('tunnels')
    if not tunnels:
        gimel_folder = dirname(dirname(dirname(abspath(__file__))))
        master_py = os.path.join(gimel_folder, 'shootback', 'master.py')

        Path('logs').mkdir(exist_ok=True)

        logs_folder = Path('logs')
        log_filename = f"rpc-tunnel-{datetime.datetime.now().strftime('%m-%d-%Y-%h-%m-%s')}"

        out_file = os.path.join(logs_folder, f"{log_filename}-out.log")
        err_file = os.path.join(logs_folder, f"{log_filename}-errors.log")
        with open(out_file, "w", encoding='utf-8') as out, \
             open(err_file, "w", encoding='utf-8') as err:

            subprocess.Popen([
                sys.executable, master_py,
                '-m', '0.0.0.0:0',
                '-c', '0.0.0.0:0',
            ], stderr=err, stdout=out, close_fds=True)

    iterations = 0
    while iterations != 20:

        tunnels = storage.get('tunnels')

        if tunnels:
            slaver_addr = random.choice(tunnels)

            slaver2public = storage.get('slaver2public')
            public_addr = slaver2public[slaver_addr]
            result = dict(slaver=slaver_addr, public=public_addr)
            return Success(result)

        iterations += 1
        sleep(0.1)

    return Error(code=101, message='Not available tunnels')


@method(name="tunnels.add")
def add_tunnel(addr, slaver_port, customer_port) -> Result:
    tunnels = storage.get('tunnels')
    tunnels.append(f'{addr}:{slaver_port}')
    tunnels = set(tunnels)
    tunnels = list(tunnels)

    storage.set('tunnels', tunnels)

    slaver2public = storage.get('slaver2public')
    slaver2public[f'{addr}:{slaver_port}'] = f'{addr}:{customer_port}'
    storage.set('slaver2public', slaver2public)
    return Success()


@method(name="tunnels.del")
def del_tunnel(host, port) -> Result:
    tunnels = storage.get('tunnels')

    addr = f'{host}:{port}'
    if addr in tunnels:
        tunnels.remove(addr)
        storage.set('tunnels', tunnels)

        slaver2public = storage.get('slaver2public')
        del slaver2public[f'{host}:{port}']
        storage.set('slaver2public', slaver2public)

    return Success()


@app.route("/", methods=["POST"])
async def router(request: Request):
    middle = dispatch_to_serializable(request.body)
    return json(middle)


def main():
    app.run('0.0.0.0', port=5000)


if __name__ == "__main__":
    main()
