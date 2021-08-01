from enum import Enum
import matplotlib.pyplot as plt
import numpy as np
import struct
import time
from threading import Thread
from queue import Queue
from typing import Tuple

from . import OSDRenderer, eprint


# see osd_command.h - osd_command_t
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


def _decode_length(b: bytes, i: int):
    l = b[i] & 0x3f
    if b[i] & 0x40:
        i += 1
        l <<= 8
        l |= b[i]
    i += 1

    return l, i


class MatPlotLibRenderer(OSDRenderer):
    def __init__(self):
        self._init = False

    def render(self, image: np.array):
        if not self._init:
            plt.ion()
            plt.show()
            self._init = True

        plt.clf()

        buffer = image.tobytes()
        image = np.frombuffer(buffer, dtype=np.uint8).reshape(*image.shape, 4)

        plt.imshow(image)
        plt.draw()
        plt.pause(0.01)

    def clear(self):
        plt.clf()
        plt.draw()
        plt.pause(0.01)


class OSD:
    def __init__(self, renderer: OSDRenderer):
        self.image = np.zeros((1, 1, 1))

        self._queue = Queue()
        self._thread = Thread(target=self._handle, args=())
        self._thread.start()

        self.renderer = renderer

    def _handle(self):
        while True:
            cmd = self._queue.get()
            if cmd is None:  # end request
                break

            eprint(cmd.id)
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
        self.flush()
        self.close()

    def exit(self):
        self._queue.put(None)
        self._thread.join()

    def set_argbrle_data(self, b: bytes,
                         num_rle: int,
                         pos: tuple,
                         dim: tuple,
                         dirty: Tuple[Tuple[int, int], Tuple[int, int]]):
        i = 0
        rle = 0

        y = 0
        x = 0

        dt = np.dtype(np.uint32)
        dt = dt.newbyteorder('<')

        sub_image = self.image[pos[1]:pos[1] + dim[1], pos[0]:pos[0] + dim[0]]
        sub_image.fill(0)

        def _color(b, i):
            return np.frombuffer(b[i:i + 4], dtype=dt)

        # t0 = time.time()
        while i < len(b):
            if x > dim[0]:
                eprint('not good, width')
            if y > dim[1]:
                eprint('not good, height')

            if b[i] != 0:  # one pixel
                sub_image[y, x] = _color(b, i)
                i += 4
                x += 1
            else:
                i += 1  # skip marker

                transparent = not bool(b[i] & 0x80)
                l, i = _decode_length(b, i)

                if transparent:
                    x += l
                    if l == 0:  # end of line marker
                        y += 1
                        x = 0
                else:
                    sub_image[y, x:x + l] = _color(b, i)
                    x += l
                    i += 4
            rle += 1

        # ARGB -> RGBA
        sub_image[:] = (sub_image >> 8) | (sub_image << 24)
        # t1 = time.time()

        # eprint('set_argbrle, rendering:', t1 - t0)

        self.renderer.render(self.image)

    def set_dimensions(self, w, h):
        self.image = np.zeros((h, w), dtype=np.uint32)

    def flush(self):
        self.image[:] = 0

    def close(self):
        self.renderer.clear()

    def process(self, cmd):
        self._queue.put(cmd)


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
