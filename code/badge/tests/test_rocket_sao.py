"""Host tests for lib/rocket_sao.py against a simulated LP5810.

Run with: python3 code/badge/tests/test_rocket_sao.py
"""

import pathlib
import sys
import time
import types
import unittest

BADGE_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BADGE_DIR))

sys.modules["machine"] = types.ModuleType("machine")
time.sleep_ms = lambda ms: None

import lib.rocket_sao as rs  # noqa: E402


class FakeLp5810:
    """Models 7-bit addresses 0x50-0x53, register pointers and auto-increment."""

    def __init__(self):
        self.regs = {}
        self.pointer = 0
        self.log = []

    def scan(self):
        return [0x50, 0x51, 0x52, 0x53]

    def writeto(self, addr, data, stop=True):
        assert 0x50 <= addr <= 0x53, hex(addr)
        self.pointer = ((addr & 3) << 8) | data[0]
        for offset, value in enumerate(data[1:]):
            self.regs[self.pointer + offset] = value
            self.log.append((self.pointer + offset, value))

    def readfrom(self, addr, nbytes):
        assert 0x50 <= addr <= 0x53, hex(addr)
        return bytes(self.regs.get(self.pointer + i, 0) for i in range(nbytes))


class FakeAdc:
    def __init__(self, uv):
        self.uv = uv

    def read_uv(self):
        return self.uv


class RocketTests(unittest.TestCase):
    def setUp(self):
        self.bus = FakeLp5810()
        self.rocket = rs.Rocket(1, i2c=self.bus, adc=FakeAdc(1_550_000))

    def test_address_carries_register_high_bits(self):
        self.assertEqual(rs.lp_addr(0x043), 0x50)
        self.assertEqual(rs.lp_addr(0x300), 0x53)

    def test_status_reads_page_three(self):
        self.bus.regs[0x300] = 0x02
        self.assertEqual(self.rocket.status(), 0x02)

    def test_init_is_manual_and_dark(self):
        self.rocket.init()
        regs = self.bus.regs
        self.assertEqual(regs[0x000], 0x01)
        self.assertEqual(regs[0x00D], 0x0B)
        self.assertEqual(regs[0x004], 0x00)
        self.assertEqual(regs[0x020], 0x0F)
        self.assertEqual([regs[0x030 + i] for i in range(4)], [0xBF] * 4)
        self.assertEqual([regs[0x040 + i] for i in range(4)], [0] * 4)

    def test_init_reports_config_error(self):
        self.bus.regs[0x300] = rs.CONFIG_ERR
        with self.assertRaises(rs.RocketError):
            self.rocket.init()

    def test_update_follows_config_changes(self):
        self.rocket.init()
        written = [reg for reg, _ in self.bus.log]
        self.assertGreater(written.index(0x010), written.index(0x004))

    def test_set_led(self):
        self.rocket.init()
        self.rocket.set_led(2, 200)
        self.assertEqual(self.bus.regs[0x042], 200)
        with self.assertRaises(ValueError):
            self.rocket.set_led(4, 1)

    def test_animation_register_layout(self):
        self.rocket.init()
        self.rocket.animate("chase")
        regs = self.bus.regs
        self.assertEqual(regs[0x004], 0x0F)
        self.assertEqual(regs[0x081], 0x0F)  # LED0 playback
        self.assertEqual([regs[0x082 + i] for i in range(5)], [255, 0, 0, 0, 255])
        self.assertEqual(regs[0x087], 0x22)  # LED0 T2/T1
        self.assertEqual(regs[0x088], 0x22)  # LED0 T4/T3
        self.assertEqual(regs[0x089], 0x01)  # LED0 AEU1 playback
        self.assertEqual(regs[0x091], 0x00)  # LED0 AEU2 skipped
        self.assertEqual(regs[0x099], 0x00)  # LED0 AEU3 skipped
        self.assertEqual(regs[0x09A + 3], 255)  # LED1 PWM2
        self.assertEqual(regs[0x0CE + 5], 255)  # LED3 PWM4
        self.assertEqual(self.bus.log[-1], (0x011, 0xFF))  # Start comes last

    def test_every_pattern_loops_without_a_jump(self):
        for name in rs.PATTERN_NAMES:
            t_code, pwms = rs.PATTERNS[name]
            self.assertEqual(len(pwms), rs.NUM_LEDS)
            self.assertLessEqual(t_code, 0xF)
            for led in pwms:
                self.assertEqual(len(led), 5)
                self.assertEqual(led[0], led[4], name)

    def test_manual_write_ends_animation(self):
        self.rocket.init()
        self.rocket.animate("breathe")
        self.rocket.set_led(0, 10)
        self.assertEqual(self.bus.regs[0x004], 0x00)
        self.assertFalse(self.rocket.animating)
        self.assertEqual(self.bus.regs[0x040], 10)

    def test_light(self):
        self.assertEqual(self.rocket.light_mv(), 1550)
        self.assertEqual(self.rocket.light_level(), 127)

    def test_rejects_bad_port(self):
        with self.assertRaises(ValueError):
            rs.Rocket(4, i2c=self.bus, adc=FakeAdc(0))


if __name__ == "__main__":
    unittest.main()
