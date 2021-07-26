#!/usr/bin/env python3

import sys
import socket
import time


def read_exact(s: socket.socket, length: int):
    data = b''
    while length != len(data):
        data += s.recv(length - len(data))
    return data


def eprint(*args, **kwargs):
    print(f'{time.time():10.3f}:', *args, file=sys.stderr, **kwargs)


class OSDRenderer:
    pass
