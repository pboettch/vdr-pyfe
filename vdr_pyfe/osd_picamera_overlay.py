import numpy as np
import time

from . import OSDRenderer, eprint

from picamera.renderers import PiOverlayRenderer


class PiCameraOverlayRenderer(OSDRenderer):
    def __init__(self, layer: int = 31):
        self.renderer = None
        self.layer = layer

    def render(self, image: np.array):
        rgba_buffer = image.tobytes()

        t0 = time.time()
        current_renderer = self.renderer
        self.renderer = PiOverlayRenderer(None, rgba_buffer,
                                          resolution=(image.shape[1], image.shape[0]),
                                          layer=self.layer,
                                          format='rgba')

        if current_renderer:
            current_renderer.close()

        t1 = time.time()
        eprint('pi-overlay renderering:', t1 - t0)

    def clear(self):
        if self.renderer:
            self.renderer.close()
