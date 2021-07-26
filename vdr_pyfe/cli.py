import argparse
import evdev
from evdev import ecodes
import selectors
import sys

from .osd import OSD
from .video import VideoPlayer
from .control import Control
from . import eprint


def main():
    parser = argparse.ArgumentParser(prog='VDR-PYFE')

    available_renderers = ['plt', 'rpi']

    parser.add_argument('-o', '--osd',
                        help='enable OSD-display',
                        type=str,
                        choices=available_renderers)
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

    if args.osd == 'rpi':
        from .osd_picamera_overlay import PiCameraOverlayRenderer
        osd = OSD(PiCameraOverlayRenderer())
    elif args.osd == 'plt':
        from .osd import MatPlotLibRenderer
        osd = OSD(MatPlotLibRenderer())
    else:
        osd = None

    video_player = VideoPlayer()
    control = Control(video_player, osd)

    control.connect(args.hostname[0])
    video_player.connect(args.hostname[0], control.video_login())

    control.send_basic_info()

    sel = selectors.DefaultSelector()
    sel.register(control.s, selectors.EVENT_READ)
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

            if device == control.s:
                control.process()

            elif device == event_device:
                for event in device.read():
                    if event.type == evdev.ecodes.EV_KEY and event.value in [1, 2]:
                        event_to_xkey = {
                            'KEY_UP': 'Up',
                            'KEY_LEFT': 'Left',
                            'KEY_RIGHT': 'Right',
                            'KEY_DOWN': 'Down',
                            'KEY_ENTER': 'Return',
                            'KEY_F1': 'F1',
                            'KEY_F2': 'F2',
                            'KEY_F3': 'F3',
                            'KEY_F4': 'F4',
                            'KEY_BACKSPACE': 'BackSpace',
                        }
                        key_event_code = ecodes.KEY[event.code]
                        k = event_to_xkey.get(key_event_code, None)
                        if k is None:
                            k = key_event_code.split('_')[1].lower()
                        eprint('key', k, ecodes.KEY[event.code])
                        control.s.send(f'KEY XKeySym {k}\r\n'.encode('utf-8'))

            elif device == video_player.s:
                video_player.process()
