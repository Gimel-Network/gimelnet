from peer import Addr, Peer


def gen_hash_from_words(words):
    import hashlib

    hash_object = hashlib.sha256()

    for word in words:
        encoded = word.encode('utf-8')
        hash_object.update(encoded)

    return str(hash_object.hexdigest())


if __name__ == '__main__':
    network = Addr('0.0.0.0', 6666)
    endpoint = "http://127.0.0.1:5000"

    uuid = gen_hash_from_words(['test', 'gimel', 'net'])
    peer = Peer(uuid, network, endpoint)
    peer.run()
