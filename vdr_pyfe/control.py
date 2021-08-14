import socket

from .video import VideoPlayer
from .osd import OSD, OSDCommand
from . import eprint, read_exact


class Control:
    def __init__(self, vp: VideoPlayer, osd: OSD):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._vp = vp
        self._video_login = ""
        self._line = b""
        self._osd = osd

    def connect(self, hostname):
        self.s.connect((hostname, 37890))
        self.s.send('CONTROL\r\n'.encode('utf-8'))

        data = self.s.recv(1024).decode('utf-8').split('\r\n')
        if not data[0].startswith('VDR') and data[0].endswith('READY'):
            eprint('error READY')
            return False

        client_id = int(data[1].split(' ')[1])

        control_sockname = self.s.getsockname()
        uint = [int(i) for i in control_sockname[0].split('.')]
        uint = (uint[0] << 24) | (uint[1] << 16) | (uint[2] << 8) | (uint[3] << 0)
        self._video_login = f'DATA {client_id} 0x{uint:08x}:{control_sockname[1]} {control_sockname[0]}'
        return True

    def video_login(self):
        return self._video_login

    def send_basic_info(self):
        self.s.send('INFO WINDOWS 1280x720\r\n'.encode('utf-8'))
        self.s.send('INFO ARGBOSD RLE\r\n'.encode('utf-8'))
        self.s.send('CONFIG\r\n'.encode('utf-8'))

    def process(self):
        b = self.s.recv(1)
        if len(b) == 0:
            eprint('error while reading - connection closed probably')
            return False

        if b == b'\n':
            self.process_line(self._line.decode('utf-8'))
            self._line = b""
        elif b == b'\r':
            pass
        else:
            self._line += b
        return True

    def osdcmd(self):
        buf = self.s.recv(1)
        if len(buf) != 1:
            eprint('error reading osdcmd')
            return

        l = int(buf[0])

        data = buf + read_exact(self.s, l - 1)

        cmd = OSDCommand(data)

        eprint(cmd)

        cmd.set_palette(read_exact(self.s, cmd.colors * 4))
        cmd.set_data(read_exact(self.s, cmd.datalen))

        if self._osd:
            self._osd.process(cmd)

    def process_line(self, line: str):
        if line.startswith('OSDCMD'):
            self.osdcmd()
        elif line.startswith('DISCARD'):
            curpos, _ = map(int, line.split(' ')[1:])  # second int: framepos
            self._vp.discard_until(curpos)
        elif line.startswith('TRICKSPEED'):
            self._vp.trickspeed(int(line.split()[1]))
        else:
            eprint('unhandled command', line)
