#!/usr/bin/env python3

import socket
import select
import sys
import struct
import os

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def read_exact(s: socket.socket, l: int):
    data = b''
    while l != len(data):
        data += s.recv(l - len(data))
    return data

if __name__ == '__main__':
    header = sys.argv[1]

    if not header.startswith('DATA'):
        eprint('header arg must start with DATA')
        sys.exit(1)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(('vdr', 37890))

    s.send((header + '\r\n').encode('utf-8'))

    data = s.recv(6).decode('utf-8')
    if data != 'DATA\r\n':
        eprint('unexpected response DATA, got', data)

    with os.fdopen(sys.stdout.fileno(), 'wb') as o:
        while True:
            data = read_exact(s, 13)
            if len(data) != 13:
                eprint('header-length failed')
                break

            pos, l, stream = struct.unpack('>QIB', data[0:13])
            eprint(pos, l, stream, len(data))

            data = read_exact(s, l)
            if len(data) != l:
                eprint('payload-data-length failed', len(data), l)
                break
            o.write(data)

    s.close()