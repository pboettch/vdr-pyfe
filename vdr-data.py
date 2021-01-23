#!/usr/bin/env python3

import socket
import select
import sys
import struct


if __name__ == '__main__':

    with open('file.dat', 'rb') as f, open('output.ts', 'wb') as o:
        data = f.read(6).decode('utf-8')
        if data != 'DATA\r\n':
            print('unexpected response DATA, got', data)

        while True:
            data = f.read(13)
            if len(data) != 13:
                print('header-length failed')
                break
            pos, l, stream = struct.unpack('>QIB', data[0:13])
            print(pos, l, stream, len(data))
            data = f.read(l)
            o.write(data)


    sys.exit(0)
    header = sys.argv[1]

    if not header.startswith('DATA'):
        print('header arg must start with DATA')
        sys.exit(1)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(('vdr', 37890))

    s.send((header + '\r\n').encode('utf-8'))

    data = s.recv(6).decode('utf-8')

    if data != 'DATA\r\n':
        print('unexpected response DATA, got', data)

    while True:
        data = s.recv(1024)

        pos, l, stream = struct.unpack('>QIB', data[0:13])

        print(pos, l, stream, len(data), l+13 == len(data))

    input()
    s.close()
