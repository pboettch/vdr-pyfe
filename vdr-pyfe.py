#!/usr/bin/env python3

import socket
import select
import sys
import struct
from threading import Thread
from subprocess import Popen, PIPE

from time import sleep

data_thread_running = False
reset_vlc = False


def read_exact(s: socket.socket, l: int):
    data = b''
    while l != len(data):
        data += s.recv(l - len(data))
    return data


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def data_thread(login: str):
    global data_thread_running
    global reset_vlc

    eprint('data-thread start')

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(('vdr', 37890))

    s.send((login + '\r\n').encode('utf-8'))

    data = s.recv(6).decode('utf-8')
    if data != 'DATA\r\n':
        eprint('unexpected response DATA, got', data)

    # with os.fdopen(sys.stdout.fileno(), 'wb') as o:

    data_thread_running = True

    total = 0

    vlc = None

    while True:
        data = read_exact(s, 13)
        if len(data) != 13:
            eprint('header-length failed')
            break

        pos, l, stream = struct.unpack('>QIB', data[0:13])
        # eprint(pos, l, stream, len(data))

        data = read_exact(s, l)
        if len(data) != l:
            eprint('payload-data-length failed', len(data), l)
            break

        total += l
        if total > 5e7:
            print('50MB received', total)
            total = 0

        if vlc is None:
            vlc = Popen(['cvlc', '-'], stdin=PIPE)

        if vlc is not None:
            vlc.stdin.write(data)

        if reset_vlc:
            if vlc is not None:
                vlc.stdin.close()
                vlc.send_signal(2)
                vlc.wait()
                vlc = None
            reset_vlc = False
    s.close()

    eprint('data-thread ended')


# see osd_command.h - osd_command_t
OSDCMD = '>BBBBqIHHHHIIQIQHHHHBB'


def osdcmd(s: socket.socket):
    buf = s.recv(1)
    if len(buf) != 1:
        eprint('error reading osdcmd')

    l = int(buf[0])
    # print('length:', l)

    data = buf + s.recv(l - 1)

    size, cmd, wnd, layer, pts, delay_ms, x, y, w, h, \
    datalen, num_rle, data_raw_data, colors, palette, \
    dirty_area_x1, dirty_area_y1, dirty_area_x2, \
    dirty_area_y2, flags, scaling = struct.unpack(OSDCMD, data)

    # print(palette, colors, size, datalen, data_raw_data)

    read_exact(s, colors * 4)
    read_exact(s, datalen)


def process_line(s: socket.socket, line: str):
    if line.startswith('OSDCMD'):
        osdcmd(s)
    elif line.startswith('STILL'):
        global reset_vlc
        reset_vlc = True
    else:
        eprint('unhandled command', line)


if __name__ == '__main__':
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((sys.argv[1], 37890))
    s.send('CONTROL\r\n'.encode('utf-8'))

    data = s.recv(1024).decode('utf-8').split('\r\n')
    if not data[0].startswith('VDR') and data[0].endswith('READY'):
        print('error READY')

    client_id = int(data[1].split(' ')[1])

    control_sockname = s.getsockname()
    uint = [int(i) for i in control_sockname[0].split('.')]
    uint = (uint[0] << 24) | (uint[1] << 16) | (uint[2] << 8) | (uint[3] << 0)
    out = f'DATA {client_id} 0x{uint:08x}:{control_sockname[1]} {control_sockname[0]}'

    print('waiting for data-thread to run')
    data_thread = Thread(target=data_thread, args=[out])
    data_thread.start()
    while not data_thread_running:
        sleep(0.1)
    print('data-thread is running')

    # s.send('INFO WINDOWS 720x576\r\n'.encode('utf-8'))
    # input()
    # s.send('INFO ARGBOSD RLE\r\n'.encode('utf-8'))
    # input()
    s.send('CONFIG\r\n'.encode('utf-8'))

    line = ""
    while True:
        b = s.recv(1)

        if len(b) == 0:
            eprint('error while reading - connection closed probably')
            break

        if b == b'\n':
            process_line(s, line)
            line = ""
        elif b == b'\r':
            pass
        else:
            line += b.decode('utf-8')

    data_thread.join()
    print("thread finished...exiting")

    s.close()
