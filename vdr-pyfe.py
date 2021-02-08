#!/usr/bin/env python3

import argparse
import evdev
from evdev import ecodes
import selectors
import socket
import struct
from subprocess import Popen, PIPE
import sys

from queue import Queue
from threading import Thread

import numpy as np
import matplotlib.pyplot as plt

from enum import Enum

from typing import Tuple

args = None
osd = None


def read_exact(s: socket.socket, l: int):
    data = b''
    while l != len(data):
        data += s.recv(l - len(data))
    return data


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


# data = read_exact(self.s, 13)
class VideoBuffer:
    HEADER_LEN = 13

    def __init__(self, header: bytearray):
        if len(header) != VideoBuffer.HEADER_LEN:
            eprint('header-length failed', len(header))
            return
        self._pos, self._length, self._stream = struct.unpack('>QIB', header)
        self._data = None

    def __str__(self):
        return f"VideoBuffer, position: {self._pos}, len: {self._length}, stream: {self._stream}"

    @property
    def stream(self):
        return self._stream

    @property
    def length(self):
        return self._length

    @property
    def type(self):
        return self._type

    def set_data(self, data: bytearray):
        if len(data) != self._length:
            eprint('insistent bytearray-length')
            return False

        self._data = data
        return True

    @property
    def data(self):
        return self._data

    def data_as_string(self):
        return self._data.decode('utf-8').strip()


class VideoPlayer:
    def __init__(self, hostname: str, login: str):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.connect((hostname.encode('utf-8'), 37890))

        self.s.send((login + '\r\n').encode('utf-8'))

        data = self.s.recv(6).decode('utf-8')
        if data != 'DATA\r\n':
            eprint('unexpected response DATA, got', data)

        self._queue = Queue()
        self._thread = Thread(target=self._handle, args=())
        self._thread.start()

        self.total = 0
        self.current_position = 0
        self.discard_until = 0

        self.vlc = None

    def __del__(self):
        self._queue.put(None)
        self._thread.join()

        self.stop_vlc()

    def _handle(self):
        while True:
            buf = self._queue.get()
            if buf is None:  # end request
                break

            if buf.stream == 255:
                info = buf.data_as_string()
                eprint('data-stream-info', info, self.current_position)
                if info.startswith('DISCARD'):
                    self.stop_vlc()
                continue

            self.start_vlc()
            self.vlc.stdin.write(buf.data)

    def start_vlc(self):
        if self.vlc is None:
            self.vlc = Popen(['vlc', '-',
                              '--intf', 'rc',
                              '--rc-host', 'localhost:23456'], stdin=PIPE)

    def stop_vlc(self):
        if self.vlc:
            self.vlc.stdin.close()
            self.vlc.send_signal(2)
            self.vlc.wait()
            self.vlc = None

    def vlc_rc_send(self, cmd: str):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(('localhost', 23456))
            sock.send(cmd.encode('utf-8'))
            sock.close()
        except:
            eprint('could not connect to vlc-rc')

    def trickspeed(self, mode: int):
        eprint('trickspeed', mode)
        if self.vlc is None:
            eprint(' vlc none')
            return

        if mode == 0:
            self.vlc_rc_send('pause\n')
        elif mode == 1:
            self.vlc_rc_send('play\n')

    def process(self):
        data = read_exact(self.s, 13)
        if len(data) != 13:
            eprint('header-length failed')
            return False

        buf = VideoBuffer(data)

        if not buf.set_data(read_exact(self.s, buf.length)):
            return False

        self._queue.put(buf)

        if self._queue.qsize() % 200 == 0:
            eprint('big queue', self._queue.qsize())

        # self.current_position = pos

        # eprint('writing', len(data))
        # if self.current_position >= self.discard_until:
        #     eprint('started')
        #     self.vlc.stdin.write(data)
        #     eprint('after write vlc')
        # else:
        #     eprint('discarding', self.current_position, self.discard_until)

        # self.total += l
        # if self.total > 5e7:
        #     eprint('50MB received')
        #     self.total = 0

        return True


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

        eprint(pos, dim, dirty)

        while i < len(b):
            if x > dim[0]:
                eprint('not good, width')
            if y > dim[1]:
                eprint('not good, height')

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

        # eprint(i, num_rle, rle )
        if args.osd:
            plt.clf()
            plt.imshow(self.image)
            plt.draw()
            plt.pause(0.01)

    def set_dimensions(self, w, h):
        self.image = np.zeros((h, w, 4), dtype=np.uint8)

    def flush(self):
        eprint('flush')
        self.image[:] = 0

    def close(self):
        eprint('close')
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

    cmd = OSDCommand(data)

    cmd.set_palette(read_exact(s, cmd.colors * 4))
    cmd.set_data(read_exact(s, cmd.datalen))

    osd.process(cmd)


def process_line(s: socket.socket, line: str, vp: VideoPlayer):
    if line.startswith('OSDCMD'):
        osdcmd(s)
    elif line.startswith('DISCARD'):
        curpos, framepos = [int(i) for i in line.split(' ')[1:]]
        # vp.discard(curpos, framepos)
    elif line.startswith('TRICKSPEED'):
        vp.trickspeed(int(line.split()[1]))
    else:
        eprint('unhandled command', line)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='VDR-PYFE')

    parser.add_argument('-o', '--osd',
                        help='enable OSD-display in with matplotlib, for debugging only',
                        action='store_true')
    parser.add_argument('--list-event-devices',
                        help='list all available input devices',
                        action='store_true')
    parser.add_argument('-e', '--event-device',
                        help='event device to be used for input',
                        type=str)
    parser.add_argument('hostname',
                        help='hostname of VDR-server',
                        nargs=1)

    args = parser.parse_args()

    if args.list_event_devices:
        eprint('available input devices (make sure adding your user to the input-group')
        for device in [evdev.InputDevice(path) for path in evdev.list_devices()]:
            eprint(' ', device.path, device.name, device.phys)
        sys.exit(0)

    osd = OSD()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((args.hostname[0], 37890))
    s.send('CONTROL\r\n'.encode('utf-8'))

    data = s.recv(1024).decode('utf-8').split('\r\n')
    if not data[0].startswith('VDR') and data[0].endswith('READY'):
        eprint('error READY')

    client_id = int(data[1].split(' ')[1])

    control_sockname = s.getsockname()
    uint = [int(i) for i in control_sockname[0].split('.')]
    uint = (uint[0] << 24) | (uint[1] << 16) | (uint[2] << 8) | (uint[3] << 0)
    login = f'DATA {client_id} 0x{uint:08x}:{control_sockname[1]} {control_sockname[0]}'

    video_player = VideoPlayer(args.hostname[0], login)

    s.send('INFO WINDOWS 1280x720\r\n'.encode('utf-8'))
    s.send('INFO ARGBOSD RLE\r\n'.encode('utf-8'))
    s.send('CONFIG\r\n'.encode('utf-8'))

    sel = selectors.DefaultSelector()
    sel.register(s, selectors.EVENT_READ)
    sel.register(video_player.s, selectors.EVENT_READ)

    if args.event_device:
        event_device = evdev.InputDevice(args.event_device)
        sel.register(event_device, selectors.EVENT_READ)
    else:
        event_device = None

    line = b""
    connected = True
    while connected:
        for key, mask in sel.select():
            device = key.fileobj
            if device == s:
                b = s.recv(1)
                if len(b) == 0:
                    eprint('error while reading - connection closed probably')
                    connected = False
                    break

                if b == b'\n':
                    process_line(s, line.decode('utf-8'), video_player)
                    line = b""
                elif b == b'\r':
                    pass
                else:
                    line += b

            elif device == event_device:
                for event in device.read():
                    if event.type == evdev.ecodes.EV_KEY and event.value in [1, 2]:
                        k = ecodes.KEY[event.code].split('_')[1].lower()
                        s.send(f'KEY {k}\r\n'.encode('utf-8'))

            elif device == video_player.s:
                video_player.process()
