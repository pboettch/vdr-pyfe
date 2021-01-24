#!/usr/bin/env python3

import socket
import select
import sys

if __name__ == '__main__':
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((sys.argv[1], 37890))
    s.send('CONTROL\r\n'.encode('utf-8'))

    data = s.recv(1024).decode('utf-8').split('\r\n')

    if not data[0].startswith('VDR') and data[0].endswith('READY'):
        print('error READY')

    client_id = int(data[1].split(' ')[1])
    print(f'client-id {client_id}')

    control_sockname = s.getsockname()
    uint = [int(i) for i in control_sockname[0].split('.')]
    uint = (uint[0] << 24) | (uint[1] << 16) | (uint[2] << 8) | (uint[3] << 0)
    out = f'./vdr-data-socket.py "DATA {client_id} 0x{uint:08x}:{control_sockname[1]} {control_sockname[0]}"'
    print(out)

    # s.send('PIPE\r\n'.encode('utf-8'))
    # data = s.recv(1024).decode('utf-8').split('\r\n')
    # print(data)

    # s.send('UDP 37890\r\n'.encode('utf-8'))
    # data = s.recv(1024).decode('utf-8').split('\r\n')
    # print(data)
    input()

    # s.send('INFO WINDOWS 720x576\r\n'.encode('utf-8'))
    # input()
    # s.send('INFO ARGBOSD RLE\r\n'.encode('utf-8'))
    # input()
    s.send('CONFIG\r\n'.encode('utf-8'))

    while True:
        data = s.recv(20000)
        txt = data.decode('utf-8').split('\r\n')
        print(len(data), txt)

    input()
    s.close()
