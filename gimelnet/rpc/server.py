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


@method(name='endpoint.get')
def endpoint_get() -> Result:
    if value := storage['actual']:
        return Success(value)
    return Error(code=404, message='Not found key.')


@method(name='endpoint.set')
def endpoint_set(host: str, port: int) -> Result:
    storage['actual'] = f'{host}:{port}'
    return Success()


@app.route("/", methods=["POST"])
async def router(request: Request):
    middle = dispatch_to_serializable(request.body)
    return json(middle)


def main():
    app.run(port=5000)


if __name__ == "__main__":
    main()