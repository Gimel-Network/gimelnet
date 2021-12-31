import os
import pathlib
import random
import subprocess
import sys
from itertools import chain
from os.path import dirname, abspath
from time import sleep

from oslash import Either
from sanic import Sanic
from sanic.request import Request
from sanic.response import json
from jsonrpcserver import Success, Error, dispatch_to_serializable, method
from jsonrpcserver.result import SuccessResult, ErrorResult
import executor

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
    if value := storage.get('endpoints'):
        print(value)
        return Success('\n'.join(value))
    return Error(code=404, message='Not found key.')


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
    started_new_tunnel = False
    tunnels = storage.get('tunnels')
    if not tunnels:
        gimel_folder = dirname(dirname(dirname(abspath(__file__))))
        master_py = os.path.join(gimel_folder, 'shootback', 'master.py')

        # proc = subprocess.Popen([
        #     sys.executable, master_py,
        #     '-m', f'0.0.0.0:0',
        #     '-c', f'0.0.0.0:0',
        # ], stderr=sys.stdout, stdout=sys.stderr)
        out = executor.execute(f'{sys.executable} {master_py} -m 0.0.0.0:0 -c 0.0.0.0:0 &')
        print(out)
        jobs = executor.execute(f'jobs')
        print(jobs)

        #
        # try:
        #     outs, errs = proc.communicate(timeout=10)
        #     print(outs, errs)
        # except subprocess.TimeoutExpired:
        #     print('Was closed')
        #     proc.kill()

    print('sleep')
    sleep(5)
    print('wakeup')

    tunnels = storage.get('tunnels')
    print(tunnels)
    if tunnels:
        slaver_addr = random.choice(tunnels)

        slaver2public = storage.get('slaver2public')
        public_addr = slaver2public[slaver_addr]
        result = dict(slaver=slaver_addr, public=public_addr)
        return Success(result)

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
