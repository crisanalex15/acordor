"""
Interfața grafică (pygame).

Ecranul are trei zone:
- bara de sus: instrumentul și microfonul (cu nivelul semnalului);
- centrul: cadranul ±50 cents, nota și indicația „strânge / slăbește”;
- jos: Auto / Cromatic, corzile instrumentului (bifate când sunt acordate)
  și calibrarea A4.

Interfața nu modifică direct modelul: `hit()` întoarce o acțiune, iar
`main.py` o aplică. Animațiile (acul cu arc, fundalul verde) țin doar de afișare.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame
import pygame.gfxdraw

from notes import IN_TUNE_CENTS, INSTRUMENTS, InstrumentString
from tuner import Hint, Mode, TunerModel

MIN_SIZE = (820, 600)
DEFAULT_SIZE = (980, 700)

BG = (12, 14, 19)
BG_TUNED = (9, 38, 28)
SURFACE = (24, 27, 35)
SURFACE_HI = (36, 40, 52)
BORDER = (48, 53, 66)
TEXT = (238, 240, 244)
MUTED = (128, 135, 150)
FAINT = (66, 72, 86)
GREEN = (52, 211, 153)
AMBER = (251, 191, 36)
RED = (248, 113, 113)
ACCENT = (99, 140, 255)

CENTS_SPAN = 50.0
ARC_HALF_DEG = 62.0
TOP_H = 68
BOTTOM_H = 190

Color = tuple[int, int, int]
Action = tuple[str, object]


@dataclass(frozen=True)
class View:
    """Tot ce are nevoie interfața ca să deseneze un cadru."""

    model: TunerModel
    devices: list[tuple[int, str]]
    device_id: int | None
    mic_error: str | None
    level: float


def _mix(a: Color, b: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t), round(a[2] + (b[2] - a[2]) * t))


def status_color(cents: float) -> Color:
    if abs(cents) <= IN_TUNE_CENTS:
        return GREEN
    if abs(cents) <= 20:
        return AMBER
    return RED


# ---- primitive anti-aliased ------------------------------------------------


def _aa_circle(surface: pygame.Surface, color: Color, center: tuple[float, float], radius: float) -> None:
    x, y, r = round(center[0]), round(center[1]), max(1, round(radius))
    pygame.gfxdraw.filled_circle(surface, x, y, r, color)
    pygame.gfxdraw.aacircle(surface, x, y, r, color)


def _aa_ring(surface: pygame.Surface, color: Color, center: tuple[float, float], radius: float, width: int) -> None:
    for i in range(width):
        pygame.gfxdraw.aacircle(surface, round(center[0]), round(center[1]), round(radius) - i, color)


def _aa_polygon(surface: pygame.Surface, color: Color, points: list[tuple[float, float]]) -> None:
    pts = [(round(x), round(y)) for x, y in points]
    pygame.gfxdraw.filled_polygon(surface, pts, color)
    pygame.gfxdraw.aapolygon(surface, pts, color)


def _aa_line(
    surface: pygame.Surface,
    color: Color,
    a: tuple[float, float],
    b: tuple[float, float],
    width: float,
    round_caps: bool = False,
) -> None:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length * width / 2, dx / length * width / 2
    _aa_polygon(surface, color, [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)])
    if round_caps:
        _aa_circle(surface, color, a, width / 2)
        _aa_circle(surface, color, b, width / 2)


def _check_mark(surface: pygame.Surface, color: Color, center: tuple[float, float], size: float) -> None:
    cx, cy = center
    p1 = (cx - size * 0.45, cy + size * 0.02)
    p2 = (cx - size * 0.12, cy + size * 0.33)
    p3 = (cx + size * 0.48, cy - size * 0.32)
    _aa_line(surface, color, p1, p2, max(2.0, size * 0.18), True)
    _aa_line(surface, color, p2, p3, max(2.0, size * 0.18), True)


class TunerUI:
    def __init__(self) -> None:
        self.menu_open = False
        self._fonts: dict[tuple[int, str], pygame.font.Font] = {}
        self._hits: list[tuple[pygame.Rect, Action]] = []
        self._mouse = (-1, -1)
        self._needle = 0.0
        self._needle_speed = 0.0
        self._glow = 0.0
        self._presence = 0.0
        self._level = 0.0
        self._hand_cursor = False

    # ---- intrare ---------------------------------------------------------

    def hit(self, pos: tuple[int, int]) -> Action | None:
        """Acțiunea de sub cursor. Ultimul element desenat (meniul) are prioritate."""
        for rect, action in reversed(self._hits):
            if rect.collidepoint(pos):
                return action
        return ("menu_close", None) if self.menu_open else None

    # ---- animație --------------------------------------------------------

    def animate(self, dt: float, view: View) -> None:
        dt = min(dt, 0.05)
        model = view.model
        reading = model.reading
        target = 0.0 if reading is None else max(-CENTS_SPAN, min(CENTS_SPAN, reading.cents))

        # arc amortizat critic: ajunge repede, fără să oscileze
        stiffness = 170.0
        damping = 2.0 * math.sqrt(stiffness)
        steps = 4
        h = dt / steps
        for _ in range(steps):
            accel = stiffness * (target - self._needle) - damping * self._needle_speed
            self._needle_speed += accel * h
            self._needle += self._needle_speed * h

        tuned = model.hint is Hint.IN_TUNE and reading is not None and not reading.holding
        self._glow += ((1.0 if tuned else 0.0) - self._glow) * min(1.0, dt * 5.0)
        present = 0.0 if reading is None else (0.45 if reading.holding else 1.0)
        self._presence += (present - self._presence) * min(1.0, dt * 8.0)
        self._level += (view.level - self._level) * min(1.0, dt * (18.0 if view.level > self._level else 5.0))

    # ---- desen -----------------------------------------------------------

    def draw(self, screen: pygame.Surface, view: View) -> None:
        self._hits.clear()
        self._mouse = pygame.mouse.get_pos()
        w, h = screen.get_size()
        bg = _mix(BG, BG_TUNED, self._glow)
        screen.fill(bg)

        avail = h - TOP_H - BOTTOM_H
        radius = max(130.0, min(w * 0.33, avail - 150.0))
        block = radius + 44 + 112
        cy = TOP_H + (avail - block) / 2 + 44 + radius
        cx = w / 2

        self._draw_dial(screen, view, cx, cy, radius, bg)
        self._draw_note(screen, view, cx, cy, radius)
        self._draw_hint(screen, view, cx, cy + 18)
        self._draw_mode_switch(screen, view, cx, h - BOTTOM_H + 8)
        self._draw_strings(screen, view, cx, h - BOTTOM_H + 98)
        self._draw_footer(screen, view, w, h)
        self._draw_top_bar(screen, view, w)
        if self.menu_open:
            self._draw_mic_menu(screen, view, w)

        hovering = any(rect.collidepoint(self._mouse) for rect, action in self._hits if action[0] != "noop")
        if hovering != self._hand_cursor:
            self._hand_cursor = hovering
            try:
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND if hovering else pygame.SYSTEM_CURSOR_ARROW)
            except pygame.error:
                pass  # driver fără cursoare de sistem (ex. randare fără fereastră)

    def _font(self, size: int, weight: str = "regular") -> pygame.font.Font:
        key = (size, weight)
        if key not in self._fonts:
            name = {"regular": "segoeui", "semibold": "segoeuisemibold", "light": "segoeuisemilight"}[weight]
            self._fonts[key] = pygame.font.SysFont(name, size)
        return self._fonts[key]

    def _text(
        self,
        surface: pygame.Surface,
        text: str,
        size: int,
        color: Color,
        weight: str = "regular",
        **anchor: object,
    ) -> pygame.Rect:
        image = self._font(size, weight).render(text, True, color)
        rect = image.get_rect(**anchor)
        surface.blit(image, rect)
        return rect

    def _fit(self, text: str, size: int, max_width: int) -> str:
        font = self._font(size)
        if font.size(text)[0] <= max_width:
            return text
        while text and font.size(text + "…")[0] > max_width:
            text = text[:-1]
        return text.rstrip() + "…"

    def _hover(self, rect: pygame.Rect) -> bool:
        return rect.collidepoint(self._mouse)

    def _button(self, surface: pygame.Surface, rect: pygame.Rect, action: Action, active: bool, radius: int) -> None:
        self._hits.append((rect, action))
        if active:
            fill = SURFACE_HI
        else:
            fill = SURFACE_HI if self._hover(rect) else SURFACE
        pygame.draw.rect(surface, fill, rect, border_radius=radius)

    # ---- bara de sus -----------------------------------------------------

    def _draw_top_bar(self, s: pygame.Surface, view: View, w: int) -> None:
        pygame.draw.line(s, (28, 31, 40), (0, TOP_H), (w, TOP_H))
        self._text(s, "Acordor", 22, TEXT, "semibold", midleft=(24, TOP_H // 2))

        seg_w, seg_h = 112, 38
        total = seg_w * len(INSTRUMENTS) + 8
        container = pygame.Rect(0, 0, total, seg_h + 8)
        container.center = (w // 2, TOP_H // 2)
        pygame.draw.rect(s, SURFACE, container, border_radius=14)
        for i, instrument in enumerate(INSTRUMENTS):
            rect = pygame.Rect(container.x + 4 + i * seg_w, container.y + 4, seg_w, seg_h)
            active = instrument.key == view.model.instrument.key
            self._hits.append((rect, ("instrument", instrument.key)))
            if active or self._hover(rect):
                pygame.draw.rect(s, SURFACE_HI if active else (30, 33, 43), rect, border_radius=11)
            color = TEXT if active else MUTED
            self._text(s, instrument.label, 16, color, "semibold" if active else "regular", center=rect.center)

        space = w - container.right - 24 - 16
        mic_w = max(170, min(300, space))
        mic = pygame.Rect(w - 24 - mic_w, container.y, mic_w, container.height)
        self._button(s, mic, ("menu_toggle", None), self.menu_open, 14)
        self._draw_mic_icon(s, (mic.x + 22, mic.centery), view.mic_error is None)

        bars_w = 34
        name_x = mic.x + 40
        name_w = mic.width - (name_x - mic.x) - bars_w - 34
        if view.mic_error:
            label, color = view.mic_error, RED
        else:
            label = next((n for i, n in view.devices if i == view.device_id), "Niciun microfon")
            color = TEXT
        self._text(s, self._fit(label, 14, name_w), 14, color, midleft=(name_x, mic.centery))

        self._draw_level_bars(s, pygame.Rect(mic.right - bars_w - 28, mic.centery - 9, bars_w, 18))
        cx, cy = mic.right - 15, mic.centery + 1
        _aa_polygon(s, MUTED, [(cx - 5, cy - 3), (cx + 5, cy - 3), (cx, cy + 3)])

    def _draw_mic_icon(self, s: pygame.Surface, center: tuple[int, int], ok: bool) -> None:
        x, y = center
        color = MUTED if ok else RED
        capsule = pygame.Rect(0, 0, 8, 13)
        capsule.midbottom = (x, y + 2)
        pygame.draw.rect(s, color, capsule, border_radius=4)
        pygame.draw.arc(s, color, pygame.Rect(x - 7, y - 9, 14, 15), math.pi, 2 * math.pi, 2)
        pygame.draw.line(s, color, (x, y + 6), (x, y + 9), 2)

    def _draw_level_bars(self, s: pygame.Surface, rect: pygame.Rect) -> None:
        bars = 5
        gap = 3
        bar_w = (rect.width - gap * (bars - 1)) / bars
        for i in range(bars):
            height = rect.height * (0.35 + 0.65 * (i + 1) / bars)
            lit = self._level >= (i + 0.5) / bars
            color = (GREEN if i < 4 else AMBER) if lit else FAINT
            bar = pygame.Rect(round(rect.x + i * (bar_w + gap)), round(rect.bottom - height), max(2, round(bar_w)), round(height))
            pygame.draw.rect(s, color, bar, border_radius=2)

    def _draw_mic_menu(self, s: pygame.Surface, view: View, w: int) -> None:
        row_h = 40
        width = 380
        rows = max(1, len(view.devices))
        menu = pygame.Rect(w - 24 - width, TOP_H - 2, width, 12 + rows * row_h)
        shadow = menu.move(0, 6)
        pygame.draw.rect(s, (5, 6, 9), shadow, border_radius=14)
        pygame.draw.rect(s, SURFACE, menu, border_radius=14)
        pygame.draw.rect(s, BORDER, menu, 1, border_radius=14)
        self._hits.append((menu, ("noop", None)))
        if not view.devices:
            self._text(s, "Nu am găsit niciun microfon.", 14, MUTED, midleft=(menu.x + 16, menu.y + 6 + row_h // 2))
            return
        for i, (device_id, name) in enumerate(view.devices):
            row = pygame.Rect(menu.x + 6, menu.y + 6 + i * row_h, menu.width - 12, row_h)
            active = device_id == view.device_id
            self._hits.append((row, ("mic", device_id)))
            if active or self._hover(row):
                pygame.draw.rect(s, SURFACE_HI, row, border_radius=10)
            if active:
                _check_mark(s, ACCENT, (row.x + 18, row.centery), 12)
            self._text(s, self._fit(name, 14, row.width - 48), 14, TEXT if active else MUTED, midleft=(row.x + 36, row.centery))

    # ---- cadran ----------------------------------------------------------

    @staticmethod
    def _polar(cx: float, cy: float, radius: float, cents: float) -> tuple[float, float]:
        theta = math.radians(cents / CENTS_SPAN * ARC_HALF_DEG)
        return cx + radius * math.sin(theta), cy - radius * math.cos(theta)

    def _sector(
        self, s: pygame.Surface, color: Color, cx: float, cy: float, inner: float, outer: float, half_cents: float
    ) -> None:
        steps = 16
        pts = [self._polar(cx, cy, outer, -half_cents + 2 * half_cents * i / steps) for i in range(steps + 1)]
        pts += [self._polar(cx, cy, inner, half_cents - 2 * half_cents * i / steps) for i in range(steps + 1)]
        _aa_polygon(s, color, pts)

    def _draw_dial(self, s: pygame.Surface, view: View, cx: float, cy: float, r: float, bg: Color) -> None:
        reading = view.model.reading
        accent = MUTED if reading is None else status_color(reading.cents)
        if view.model.hint is Hint.WRONG_STRING:
            accent = RED

        # zona „acordat”: o bandă verde pe exterior, care se umple când nota e acordată
        self._sector(s, _mix(bg, GREEN, 0.55), cx, cy, r + 9, r + 14, IN_TUNE_CENTS)
        if self._glow > 0.02:
            self._sector(s, _mix(bg, GREEN, 0.18 * self._glow), cx, cy, r - 40, r + 4, IN_TUNE_CENTS)

        for i in range(-20, 21):
            cents = i * 2.5
            major = i % 10 == 0
            mid = i % 4 == 0
            length = 26 if i == 0 else (20 if major else (14 if mid else 9))
            width = 3.2 if major else (2.4 if mid else 1.8)
            base = MUTED if major else (FAINT if mid else _mix(bg, FAINT, 0.8))
            near = max(0.0, 1.0 - abs(cents - self._needle) / 7.0) * self._presence
            color = _mix(base, accent, near)
            _aa_line(s, color, self._polar(cx, cy, r - length, cents), self._polar(cx, cy, r, cents), width)
            if major:
                label = "0" if i == 0 else f"{cents:+.0f}".replace("-", "−")
                lx, ly = self._polar(cx, cy, r + 20, cents)
                self._text(s, label, 13, MUTED, center=(lx, ly))

        # indicatorul
        if self._presence > 0.02:
            color = _mix(_mix(bg, FAINT, 1.0), accent, self._presence)
            a = self._polar(cx, cy, r - 48, self._needle)
            b = self._polar(cx, cy, r + 6, self._needle)
            _aa_line(s, color, a, b, 7, round_caps=True)
            tip = self._polar(cx, cy, r + 6, self._needle)
            _aa_circle(s, color, tip, 7)
            _aa_circle(s, _mix(color, TEXT, 0.6), tip, 3)

    def _draw_note(self, s: pygame.Surface, view: View, cx: float, cy: float, r: float) -> None:
        model = view.model
        reading = model.reading
        size = max(64, int(r * 0.56))
        center_y = cy - r * 0.47

        if reading is not None:
            note = reading.target
            color = _mix(TEXT, GREEN, self._glow)
            if reading.holding:
                color = _mix(color, BG, 0.45)
        elif model.mode is Mode.STRING and model.selected is not None:
            note, color = model.selected.note, FAINT
        else:
            note, color = None, FAINT

        if note is None:
            tuning = "  ".join(st.note.name.replace("#", "♯") for st in model.instrument.strings)
            if model.mode is Mode.CHROMATIC:
                tuning = "C  D  E  F  G  A  B"
            self._text(s, tuning, max(22, size // 4), FAINT, "light", center=(cx, center_y + size * 0.15))
        else:
            letter = self._text(s, note.letter, size, color, "semibold", center=(cx, center_y))
            small = max(20, int(size * 0.34))
            if note.accidental:
                self._text(s, "♯", small + 4, color, "regular", topleft=(letter.right - 2, letter.top + size * 0.12))
            self._text(s, str(note.octave), small, _mix(color, BG, 0.35), "semibold", bottomleft=(letter.right + 2, letter.bottom - size * 0.2))

        caption_y = center_y + size * 0.62
        if reading is None:
            caption = {
                Mode.AUTO: f"Auto · {model.instrument.label.lower()}",
                Mode.CHROMATIC: "Cromatic · orice notă",
                Mode.STRING: f"Coarda {model.selected.number}" if model.selected else "",
            }[model.mode]
            self._text(s, caption, 15, MUTED, center=(cx, caption_y))
        else:
            cents = reading.cents
            if abs(cents) >= 100:
                text = f"{cents / 100:+.0f} semitonuri"
            elif abs(cents) >= 0.5:
                text = f"{cents:+.0f} cents"
            else:
                text = "0 cents"
            text = text.replace("-", "−")
            color = _mix(MUTED, status_color(cents), self._presence)
            self._text(s, text, 20, color, "semibold", center=(cx, caption_y))

    def _draw_hint(self, s: pygame.Surface, view: View, cx: float, top: float) -> None:
        model = view.model
        reading = model.reading
        hint = model.hint

        if view.mic_error:
            text, color = "Verifică microfonul din dreapta sus", RED
        elif hint is Hint.IDLE:
            text = "Cântă o notă" if model.mode is Mode.CHROMATIC else "Ciupește o coardă"
            color = MUTED
        elif hint is Hint.IN_TUNE:
            text, color = "Acordat", GREEN
        elif hint is Hint.WRONG_STRING:
            text, color = f"Aud {reading.heard.label} — e coarda corectă?", RED
        elif hint is Hint.TOO_LOW:
            text = "Prea jos — strânge cheia" if model.mode is not Mode.CHROMATIC else "Prea jos"
            color = status_color(reading.cents)
        else:
            text = "Prea sus — slăbește cheia" if model.mode is not Mode.CHROMATIC else "Prea sus"
            color = status_color(reading.cents)

        image = self._font(17, "semibold").render(text, True, color)
        pill = pygame.Rect(0, 0, image.get_width() + 40, 42)
        pill.midtop = (round(cx), round(top))
        pygame.draw.rect(s, _mix(SURFACE, color, 0.10 if hint is not Hint.IDLE else 0.0), pill, border_radius=21)
        s.blit(image, image.get_rect(center=pill.center))

        if reading is not None:
            info = f"{reading.frequency:.1f} Hz   ·   țintă {reading.target.label} = {reading.target_hz:.2f} Hz"
            if reading.holding:
                info += "   ·   ultima citire"
            self._text(s, info, 14, MUTED, midtop=(cx, pill.bottom + 12))

    # ---- jos -------------------------------------------------------------

    def _draw_mode_switch(self, s: pygame.Surface, view: View, cx: float, top: float) -> None:
        options = (("Auto", "auto", Mode.AUTO), ("Cromatic", "chromatic", Mode.CHROMATIC))
        seg_w, seg_h = 110, 34
        container = pygame.Rect(0, round(top), seg_w * len(options) + 8, seg_h + 8)
        container.centerx = round(cx)
        pygame.draw.rect(s, SURFACE, container, border_radius=13)
        for i, (label, action, mode) in enumerate(options):
            rect = pygame.Rect(container.x + 4 + i * seg_w, container.y + 4, seg_w, seg_h)
            active = view.model.mode is mode
            self._hits.append((rect, (action, None)))
            if active:
                pygame.draw.rect(s, ACCENT, rect, border_radius=10)
            elif self._hover(rect):
                pygame.draw.rect(s, SURFACE_HI, rect, border_radius=10)
            self._text(s, label, 15, TEXT if active else MUTED, "semibold" if active else "regular", center=rect.center)

    def _draw_strings(self, s: pygame.Surface, view: View, cx: float, cy: float) -> None:
        model = view.model
        strings = model.instrument.strings
        radius = 30
        gap = 22
        total = len(strings) * radius * 2 + (len(strings) - 1) * gap
        x0 = cx - total / 2 + radius
        reading = model.reading
        target_number = reading.target_string.number if reading and reading.target_string else None

        for i, string in enumerate(strings):
            x = x0 + i * (radius * 2 + gap)
            self._draw_peg(s, string, (x, cy), radius, model, target_number)

    def _draw_peg(
        self,
        s: pygame.Surface,
        string: InstrumentString,
        center: tuple[float, float],
        radius: int,
        model: TunerModel,
        target_number: int | None,
    ) -> None:
        x, y = center
        rect = pygame.Rect(0, 0, radius * 2 + 8, radius * 2 + 26)
        rect.midtop = (round(x), round(y - radius - 4))
        self._hits.append((rect, ("string", string.number)))

        selected = model.mode is Mode.STRING and model.selected == string
        tuned = string.number in model.tuned
        listening = target_number == string.number and model.reading is not None

        if selected:
            fill = ACCENT
        elif tuned:
            fill = _mix(SURFACE, GREEN, 0.22)
        else:
            fill = SURFACE_HI if self._hover(rect) else SURFACE
        _aa_circle(s, fill, center, radius)

        if listening:
            ring = status_color(model.reading.cents) if model.reading else MUTED
            _aa_ring(s, _mix(FAINT, ring, self._presence), center, radius + 5, 3)
        elif not selected:
            _aa_ring(s, GREEN if tuned else BORDER, center, radius, 1)

        note = string.note
        color = TEXT
        label = self._text(s, note.letter + ("♯" if note.accidental else ""), 21, color, "semibold", center=(x - 4, y))
        self._text(s, str(note.octave), 12, _mix(color, fill, 0.35), "semibold", bottomleft=(label.right, label.bottom - 6))

        self._text(s, str(string.number), 12, MUTED, center=(x, y + radius + 13))

        if tuned:
            badge = (x + radius * 0.72, y - radius * 0.72)
            _aa_circle(s, GREEN, badge, 10)
            _check_mark(s, BG, badge, 10)

    def _draw_footer(self, s: pygame.Surface, view: View, w: int, h: int) -> None:
        y = h - 24
        keys = "A auto  ·  C cromatic  ·  1–6 coarda  ·  I instrument  ·  M microfon"
        self._text(s, keys, 12, FAINT, midleft=(24, y))

        minus = pygame.Rect(0, 0, 28, 28)
        plus = pygame.Rect(0, 0, 28, 28)
        plus.midright = (w - 24, y)
        minus.midright = (plus.left - 6, y)
        for rect, label, step in ((minus, "−", -1), (plus, "+", 1)):
            self._button(s, rect, ("a4", step), False, 8)
            self._text(s, label, 18, TEXT, center=(rect.centerx, rect.centery - 1))
        self._text(s, f"A4 = {view.model.a4:.0f} Hz", 14, MUTED, midright=(minus.left - 10, y))
