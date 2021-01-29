#!/usr/bin/env python3

import socket
import argparse
import sys
import struct
from threading import Thread
from subprocess import Popen, PIPE

import numpy as np
import matplotlib.pyplot as plt

from enum import Enum

from typing import Tuple

from time import sleep

data_thread_running = False
reset_vlc = False
args = None
osd = None

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
            vlc = Popen(['cvlc', '-', '--intf', 'dummy'], stdin=PIPE)

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


class OSDCommandId(Enum):
    OSD_Nop = 0  # Do nothing ; used to initialize delay_ms counter
    OSD_Size = 1  # Set size of VDR OSD area (usually 720x576)
    OSD_Set_RLE = 2  # Create/update OSD window. Data is rle-compressed.
    OSD_Close = 5  # Close OSD window
    OSD_Commit = 7  # All OSD areas have been updated, commit changes to display
    OSD_Flush = 8  # Flush all pending OSD operations immediately
    OSD_VideoWindow = 9  # Set video window inside OSD
    OSD_Set_HDMV = 10  # Create/update OSD window. Data is RLE compressed.
    OSD_Set_LUT8 = 11  # Create/update OSD window. Data is uncompressed.
    OSD_Set_ARGB = 12  # Create/update OSD window. Data is uncompressed.
    OSD_Set_ARGBRLE = 13  # Create/update OSD window. Data is RLE compressed.


class OSD:
    def __init__(self):
        self.image = np.zeros((1, 1, 1))

        if args.osd:
            plt.ion()
            plt.show()

    def _decode_length(self, b: bytes, i: int):
        l = b[i] & 0x3f
        if b[i] & 0x40:
            i += 1
            l <<= 8
            l |= b[i]
        i += 1

        return l, i

    def set_argbrle_data(self, b: bytes,
                         num_rle: int,
                         pos: tuple,
                         dim: tuple,
                         dirty: Tuple[Tuple[int, int], Tuple[int, int]]):

        i = 0
        rle = 0

        y = 0
        x = 0

        sub_image = self.image[pos[1]:pos[1] + dim[1], pos[0]:pos[0] + dim[0]]
        sub_image[::] = 0

        print(pos, dim, dirty)

        while i < len(b):
            if x > dim[0]:
                print('not good, width')
            if y > dim[1]:
                print('not good, height')

            if b[i] != 0:
                # one pixel
                c = struct.unpack('BBBB', b[i:i + 4])
                sub_image[y, x] = [c[1], c[2], c[3], c[0]]
                # eprint('pixel', argb)
                i += 4

                x += 1
            else:
                i += 1  # skip marker

                transparent = not bool(b[i] & 0x80)
                l, i = self._decode_length(b, i)

                if transparent:
                    x += l
                    if l == 0:  # end of line marker
                        y += 1
                        x = 0
                else:
                    c = struct.unpack('BBBB', b[i:i + 4])
                    sub_image[y, x:x + l] = [c[1], c[2], c[3], c[0]]
                    x += l
                    i += 4

            rle += 1

        # print(i, num_rle, rle )
        if args.osd:
            plt.clf()
            plt.imshow(self.image)
            plt.draw()
            plt.pause(0.01)

    def set_dimensions(self, w, h):
        self.image = np.zeros((h, w, 4), dtype=np.uint8)

    def flush(self):
        print('flush')
        self.image[:] = 0

    def close(self):
        print('close')
        if args.osd:
            plt.clf()
            plt.draw()
            plt.pause(0.01)

    def process(self, cmd):
        if cmd.id == OSDCommandId.OSD_Set_ARGBRLE:
            self.set_argbrle_data(cmd.data_raw_data, cmd.num_rle,
                                  (cmd.x, cmd.y), (cmd.w, cmd.h),
                                  ((cmd.dirty_area_x1, cmd.dirty_area_y1),
                                   (cmd.dirty_area_x2, cmd.dirty_area_y2)))
        elif cmd.id == OSDCommandId.OSD_Size:
            self.set_dimensions(cmd.w, cmd.h)
        elif cmd.id == OSDCommandId.OSD_Close:
            self.close()
        elif cmd.id == OSDCommandId.OSD_Flush:
            self.flush()
        else:
            eprint('unhandled osd-command', cmd.id)


class OSDCommand():
    OSDCMD_STRUCT = '>BBBBqIHHHHIIQIQHHHHBB'

    def __init__(self, raw_data: bytes, file=None):
        self.f = file

        if self.f:
            self.f.write(raw_data)

        self.size, self.id, self.wnd, self.layer, self.pts, self.delay_ms, \
        self.x, self.y, self.w, self.h, self.datalen, self.num_rle, self.data_raw_data, \
        self.colors, self.palette, self.dirty_area_x1, self.dirty_area_y1, \
        self.dirty_area_x2, self.dirty_area_y2, self.flags, self.scaling = \
            struct.unpack(self.OSDCMD_STRUCT, raw_data)

        self.id = OSDCommandId(self.id)

        self.osd = OSD()

    def __str__(self):
        return f'OSD-Command: {self.id}, wnd: {self.wnd}, lay: {self.layer}, pts: {self.pts} ' \
               f'delay: {self.delay_ms}, x: {self.x}, y: {self.y}, w: {self.w}, h: {self.h} ' \
               f'data_len: {self.datalen}, num_rle: {self.num_rle}, colors: {self.colors} ' \
               f'dirty_area: {self.dirty_area_x1} {self.dirty_area_y1} {self.dirty_area_x2} {self.dirty_area_y2} ' \
               f'flags: {self.flags:05b}b, scaling: {self.scaling}'

    def set_data(self, data: bytes):
        if self.f:
            self.f.write(data)
        self.data_raw_data = data

    def set_palette(self, palette: bytes):
        if self.f:
            self.f.write(palette)
        self.palette = palette


# see osd_command.h - osd_command_t


def osdcmd(s: socket.socket):
    buf = s.recv(1)
    if len(buf) != 1:
        eprint('error reading osdcmd')

    l = int(buf[0])

    data = buf + read_exact(s, l - 1)

    cmd = OSDCommand(data, open('osd.data', 'ab'))

    cmd.set_palette(read_exact(s, cmd.colors * 4))
    cmd.set_data(read_exact(s, cmd.datalen))

    osd.process(cmd)


def process_line(s: socket.socket, line: str):
    if line.startswith('OSDCMD'):
        osdcmd(s)
    elif line.startswith('STILL'):
        global reset_vlc
        reset_vlc = True
    else:
        eprint('unhandled command', line)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='VDR-PYFE')

    parser.add_argument('-o', '--osd',
                        help='enable OSD-display in with matplotlib, for debugging only',
                        action='store_true')
    parser.add_argument('hostname',
                        help='hostname of VDR-server',
                        nargs=1)

    args = parser.parse_args()

    osd = OSD()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((args.hostname[0], 37890))
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

    s.send('INFO WINDOWS 1280x720\r\n'.encode('utf-8'))
    s.send('INFO ARGBOSD RLE\r\n'.encode('utf-8'))
    s.send('CONFIG\r\n'.encode('utf-8'))

    line = b""
    while True:
        b = s.recv(1)

        if len(b) == 0:
            eprint('error while reading - connection closed probably')
            break

        if b == b'\n':
            process_line(s, line.decode('utf-8'))
            line = b""
        elif b == b'\r':
            pass
        else:
            line += b

    data_thread.join()
    print("thread finished...exiting")

    s.close()
