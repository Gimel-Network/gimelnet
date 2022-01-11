from gimelnet.core.peerjrpc import SanicPeer
from peer import Peer
import click


def gen_hash_from_words(words):
    import hashlib

    hash_object = hashlib.sha256()

    for word in words:
        encoded = word.encode('utf-8')
        hash_object.update(encoded)

    return str(hash_object.hexdigest())


@click.group()
def cli():
    pass


@click.command(name='run')
@click.option('--rpc', required=True, help='RPC address')
def run(rpc):
    uuid = gen_hash_from_words(['test', 'gimel', 'net'])
    peer = SanicPeer(rpc, uuid)
    peer.run()


cli.add_command(run)

if __name__ == '__main__':
    cli()