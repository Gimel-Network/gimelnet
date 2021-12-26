from peer import Addr, Peer


def gen_hash_from_words(words):
    import hashlib

    hash_object = hashlib.sha256()

    for word in words:
        encoded = word.encode('utf-8')
        hash_object.update(encoded)

    return str(hash_object.hexdigest())


if __name__ == '__main__':
    endpoint = "http://65.21.240.183:5000"

    uuid = gen_hash_from_words(['test', 'gimel', 'net'])
    peer = Peer(uuid, endpoint)
    peer.run()
