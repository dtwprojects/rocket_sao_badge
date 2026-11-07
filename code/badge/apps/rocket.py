"""Rocket SAO app: LED animations and an ambient light meter."""

import lvgl

from apps.base_app import BaseApp
from lib.button import UserA, UserB
from lib.epd import display
from lib.led_bar import NUM_LEDS, leds
from lib.rocket_sao import PATTERN_NAMES, Rocket

ROCKET_PORT = 1  # The SAO header the rocket is plugged into: 1, 2 or 3

_WHITE = lvgl.color_hex(0xFFFFFF)
_BLACK = lvgl.color_hex(0x000000)
_FONT = lvgl.font_montserrat_48

_TICKS_PER_SAMPLE = 5
_MIN_CURRENT = 16
_MAX_CURRENT = 0xBF
_BAR_ON = (0, 2, 0)
_BAR_MISSING = (3, 0, 0)


def _current_for_light(level: int) -> int:
    """Dim the LEDs in the dark and raise them in bright light."""
    return _MIN_CURRENT + level * (_MAX_CURRENT - _MIN_CURRENT) // 255


class RocketApp(BaseApp):
    def __init__(self, name: str | None = None) -> None:
        self.name = "Rocket"
        self.sleep_ms = 100
        self.launched = False
        self.rocket = None
        self.connected = False
        self.pattern_idx = 0
        self.follow_light = False
        self.ticks = 0

    def _draw_screen(self):
        scr = lvgl.obj()
        scr.remove_style_all()
        scr.set_size(lvgl.pct(100), lvgl.pct(100))
        scr.set_style_bg_color(_WHITE, 0)
        scr.set_style_bg_opa(lvgl.OPA.COVER, 0)

        text = lvgl.label(scr)
        text.set_text("Rocket SAO\n\nA: next animation\nB: follow ambient light")
        text.set_style_text_color(_BLACK, 0)
        text.set_style_text_font(_FONT, 0)
        text.center()

        lvgl.screen_load(scr)
        scr.update_layout()
        lvgl.refr_now(display.lv_display)
        display.update()

    def _connect(self) -> bool:
        """Bring up the rocket, returning False if it isn't there yet."""
        if self.rocket is None:
            self.rocket = Rocket(ROCKET_PORT)
        if not self.rocket.present():
            return False
        self.rocket.init()
        self.rocket.animate(PATTERN_NAMES[self.pattern_idx])
        print(f"Rocket found, running {PATTERN_NAMES[self.pattern_idx]}")
        return True

    def _show_level(self, level: int):
        lit = (level * NUM_LEDS + 127) // 255
        leds.set([_BAR_ON if i < lit else (0, 0, 0) for i in range(NUM_LEDS)])
        leds.write()

    def _show_missing(self):
        leds.set([_BAR_MISSING] + [(0, 0, 0)] * (NUM_LEDS - 1))
        leds.write()

    def run(self):
        if self.launched:
            self._draw_screen()
            self.connected = False

        self.ticks += 1
        due = self.ticks % _TICKS_PER_SAMPLE == 0

        if not self.connected:
            if self.launched or due:
                self.connected = self._connect()
                if not self.connected:
                    self._show_missing()
            return

        try:
            self._update(due)
        except OSError as ex:
            print(f"Rocket lost: {ex}")
            self.connected = False
            self._show_missing()

    def _update(self, due: bool):
        if UserA.pressed():
            self.pattern_idx = (self.pattern_idx + 1) % len(PATTERN_NAMES)
            self.rocket.animate(PATTERN_NAMES[self.pattern_idx])
            print(f"Rocket pattern: {PATTERN_NAMES[self.pattern_idx]}")

        if UserB.pressed():
            self.follow_light = not self.follow_light
            print(f"Rocket follow light: {self.follow_light}")
            if not self.follow_light:
                self.rocket.set_current(_MAX_CURRENT)

        if due:
            level = self.rocket.light_level()
            self._show_level(level)
            if self.follow_light:
                self.rocket.set_current(_current_for_light(level))
