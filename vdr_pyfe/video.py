from subprocess import Popen, PIPE
from queue import Queue
import selectors
import socket
import struct
from threading import Thread

from . import eprint, read_exact


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
    def position(self):
        return self._pos

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

    def guck_mal(self):
        if self._length % 188:
            print('not multiple 188')
            return

        for i in range(0, self._length, 188):
            if self._data[i] != 0x47:
                print('not TS')
                continue

            if not self._data[i + 1] & 0x40:
                continue

            offset = 4
            if self._data[i + 3] & 0x20:
                offset = 5 + self._data[i + 4]

            print('pusi', offset, self._data[i + offset:i + offset + 3])

            if self._data[i + offset:i + offset + 3] != b'\0\0\1':
                continue
            print('PES')

            AUDIO_STREAM_MASK = ~0x1F
            VIDEO_STREAM_MASK = ~0x0F
            AUDIO_STREAM = 0xC0
            VIDEO_STREAM = 0xE0
            if self._data[i + offset + 3] & VIDEO_STREAM_MASK == VIDEO_STREAM:
                print('VIDEO')

            if self._data[i + offset + 6] & 0xc0 != 0x80:
                print('no PTS')

            if self._data[i + offset + 6] & 0x30 != 0:
                print('no PTS')

            if self._data[i + offset + 7] & 0x80:
                b = self._data[i + offset + 9: i + offset + 14]
                ts = (b[0] & 0x0e) << 29
                ts |= (b[1]) << 22
                ts |= (b[2] & 0xfe) << 14
                ts |= (b[3]) << 7
                ts |= (b[4] & 0xfe) >> 1
                print('pts', ts, self._pos)


#   if (IS_VIDEO_PACKET(buf) || IS_AUDIO_PACKET(buf)) {
#
#     if ((buf[6] & 0xC0) != 0x80)
#       return NO_PTS;
#     if ((buf[6] & 0x30) != 0)
#       return NO_PTS;
#
#     if ((len > 13) && (buf[7] & 0x80)) { /* pts avail */
#       return parse_timestamp(buf + 9);
#     }
#   }
#   return NO_PTS;

# define IS_VIDEO_PACKET(data)      (VIDEO_STREAM    == ((data)[3] & ~VIDEO_STREAM_MASK))
# define IS_MPEG_AUDIO_PACKET(data) (AUDIO_STREAM    == ((data)[3] & ~AUDIO_STREAM_MASK))
# define IS_PS1_PACKET(data)        (PRIVATE_STREAM1 == (data)[3])
# define IS_PADDING_PACKET(data)    (PADDING_STREAM  == (data)[3])
# define IS_AUDIO_PACKET(data)      (IS_MPEG_AUDIO_PACKET(data) || IS_PS1_PACKET(data))
# define PRIVATE_STREAM1   0xBD
# define PADDING_STREAM    0xBE
# define PRIVATE_STREAM2   0xBF
# define AUDIO_STREAM_S    0xC0      /* 1100 0000 */
# define AUDIO_STREAM_E    0xDF      /* 1101 1111 */
# define VIDEO_STREAM_S    0xE0      /* 1110 0000 */
# define VIDEO_STREAM_E    0xEF      /* 1110 1111 */


class VideoPlayer:
    def __init__(self):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self._queue = Queue(maxsize=50)
        self._thread = Thread(target=self._handle, args=())
        self._thread.start()

        # self.total = 0
        # self.current_position = 0
        self._discard_timestamp = 0

        self._reader_thread_running = False
        self._reader_thread = Thread(target=self._reader, args=())

        self.vlc = None

    def connect(self, hostname: str, login: str):
        self.s.connect((hostname.encode('utf-8'), 37890))
        self.s.send((login + '\r\n').encode('utf-8'))

        data = self.s.recv(6).decode('utf-8')
        if data != 'DATA\r\n':
            eprint('unexpected response DATA, got', data)
            return False

        self._reader_thread_running = True
        self._reader_thread.start()

        return True

    def exit(self):
        eprint('closing socket')
        self._reader_thread_running = False
        self._reader_thread.join()

        self._queue.put(None)
        self._thread.join()

    def _reader(self):
        sel = selectors.DefaultSelector()
        sel.register(self.s, selectors.EVENT_READ)

        while self._reader_thread_running:
            for key, mask in sel.select(timeout=1):
                device = key.fileobj
                assert device == self.s

                data = read_exact(self.s, 13)
                if len(data) != 13:
                    eprint('header-length failed')
                    self._reader_thread_running = False
                    break

                buf = VideoBuffer(data)

                if not buf.set_data(read_exact(self.s, buf.length)):
                    self._reader_thread_running = False
                    break

                self._queue.put(buf)

                if self._queue.qsize() > 200 == 0:
                    eprint('big queue', self._queue.qsize())

        eprint('video-reader-thread has ended')

    def _handle(self):
        while True:
            buf = self._queue.get()
            if buf is None:  # end request
                break
            self._queue.task_done()

            if buf.stream == 255:
                info = buf.data_as_string()
                eprint('data-stream-info', info)
                if info.startswith('DISCARD'):
                    self.vlc_rc_send('next\n')
                    # self.stop_vlc()
                continue

            if self._discard_timestamp > buf.position:
                print(f'discarding f{buf}')
                continue

            self.start_vlc()
            # buf.guck_mal()

            # print(f'writing {buf} to vlc')
            self.vlc.stdin.write(buf.data)
            # self.output.write(buf.data)

        self.stop_vlc()

    def start_vlc(self):
        if self.vlc is None:
            self.vlc = Popen(['vlc', '-',
                              '--intf', 'rc',
                              '--rc-host', 'localhost:23456'], stdin=PIPE)
            # self.output = open('stream.ts', 'wb')

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

    def discard_until(self, ts):
        self._discard_timestamp = ts
