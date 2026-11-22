"""
Acordor pentru chitară, bass și ukulele.

Fluxul unui cadru (60 pe secundă):
    microfon → ring buffer → YIN (pitch.py) → stabilizare (tracker.py)
    → coarda țintă și cents (tuner.py) → desen (ui.py)

Pornire:  python main.py
"""

from __future__ import annotations

import time

import numpy as np
import pygame

from audio_capture import AudioCapture, default_input_device_id, list_input_devices
from notes import INSTRUMENTS
from pitch import analysis_size, estimate_pitch
from tuner import TunerModel
from ui import DEFAULT_SIZE, MIN_SIZE, TunerUI, View

FPS = 60
LEVEL_FLOOR_DB = -75.0


def _level(samples: np.ndarray) -> float:
    """Nivelul semnalului pe 0..1, pe scară logaritmică (−75 dBFS … 0 dBFS)."""
    if samples.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    db = 20.0 * np.log10(max(rms, 1e-9))
    return float(np.clip((db - LEVEL_FLOOR_DB) / -LEVEL_FLOOR_DB, 0.0, 1.0))


class App:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("Acordor")
        self.screen = pygame.display.set_mode(DEFAULT_SIZE, pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.ui = TunerUI()
        self.model = TunerModel()

        self.devices = list_input_devices()
        self.capture = AudioCapture(default_input_device_id(self.devices))
        self.mic_error: str | None = None
        self.level = 0.0
        self._last_frames = -1
        self._open_mic(self.capture.device_id)

    # ---- microfon --------------------------------------------------------

    def _open_mic(self, device_id: int | None) -> None:
        if device_id is None:
            self.mic_error = "Niciun microfon găsit"
            return
        try:
            self.capture.set_device(device_id)
            self.mic_error = None
        except Exception:  # PortAudio aruncă tipuri diferite pe fiecare host API
            self.capture.stop()
            self.mic_error = "Nu pot deschide microfonul"
        self.model.feed(None, time.monotonic())
        self._last_frames = -1

    def _cycle_mic(self) -> None:
        ids = [device_id for device_id, _ in self.devices]
        if not ids:
            return
        current = self.capture.device_id
        index = (ids.index(current) + 1) % len(ids) if current in ids else 0
        self._open_mic(ids[index])

    # ---- acțiuni ---------------------------------------------------------

    def _apply(self, action: tuple[str, object] | None) -> None:
        if action is None:
            return
        kind, value = action
        if kind != "menu_toggle" and kind != "noop":
            self.ui.menu_open = False
        if kind == "instrument":
            self.model.set_instrument(next(i for i in INSTRUMENTS if i.key == value))
        elif kind == "auto":
            self.model.set_auto()
        elif kind == "chromatic":
            self.model.set_chromatic()
        elif kind == "string":
            self.model.select_string(int(value))  # type: ignore[arg-type]
        elif kind == "a4":
            self.model.nudge_a4(float(value))  # type: ignore[arg-type]
        elif kind == "menu_toggle":
            self.devices = list_input_devices() if not self.ui.menu_open else self.devices
            self.ui.menu_open = not self.ui.menu_open
        elif kind == "mic" and value != self.capture.device_id:
            self._open_mic(int(value))  # type: ignore[arg-type]

    def _on_key(self, key: int) -> bool:
        """Întoarce False dacă aplicația trebuie închisă."""
        if key == pygame.K_ESCAPE:
            if self.ui.menu_open:
                self.ui.menu_open = False
                return True
            return False
        if key == pygame.K_a:
            self._apply(("auto", None))
        elif key == pygame.K_c:
            self._apply(("chromatic", None))
        elif key == pygame.K_m:
            self._cycle_mic()
        elif key == pygame.K_i:
            keys = [i.key for i in INSTRUMENTS]
            nxt = keys[(keys.index(self.model.instrument.key) + 1) % len(keys)]
            self._apply(("instrument", nxt))
        elif key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self._apply(("a4", 1))
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self._apply(("a4", -1))
        elif pygame.K_1 <= key <= pygame.K_9:
            self._apply(("string", key - pygame.K_0))
        return True

    # ---- bucla -----------------------------------------------------------

    def _analyse(self, now: float) -> None:
        if not self.capture.running or self.capture.frames_written == self._last_frames:
            self.model.tick(now)
            return
        self._last_frames = self.capture.frames_written
        instrument = self.model.instrument
        rate = self.capture.sample_rate
        window = self.capture.get_window(analysis_size(rate, instrument.fmin))
        self.level = _level(window[-2048:])
        self.model.feed(estimate_pitch(window, rate, instrument.fmin, instrument.fmax), now)

    def run(self) -> None:
        running = True
        try:
            while running:
                dt = self.clock.tick(FPS) / 1000.0
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        running = self._on_key(event.key)
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        self._apply(self.ui.hit(event.pos))
                    elif event.type == pygame.VIDEORESIZE:
                        if event.w < MIN_SIZE[0] or event.h < MIN_SIZE[1]:
                            size = (max(event.w, MIN_SIZE[0]), max(event.h, MIN_SIZE[1]))
                            self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)

                self._analyse(time.monotonic())
                view = View(
                    model=self.model,
                    devices=self.devices,
                    device_id=self.capture.device_id,
                    mic_error=self.mic_error,
                    level=self.level if self.capture.running else 0.0,
                )
                self.ui.animate(dt, view)
                self.ui.draw(pygame.display.get_surface(), view)
                pygame.display.flip()
        finally:
            self.capture.stop()
            pygame.quit()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
