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
time.ticks_ms = lambda: int(time.monotonic() * 1000)
time.ticks_add = lambda ticks, delta: ticks + delta
time.ticks_diff = lambda a, b: a - b

import lib.rocket_sao as rs  # noqa: E402
import lib.tiny_flash as tf  # noqa: E402


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


class FakeBoard(FakeLp5810):
    """An LP5810 plus the ATtiny target firmware at 0x2A."""

    def __init__(self):
        super().__init__()
        self.tiny = {0x00: 0x52, 0x01: 7, 0x10: 0xFF, 0x11: 0x01}
        self.tiny_pointer = 0

    def scan(self):
        return [0x2A] + super().scan()

    def writeto(self, addr, data, stop=True):
        if addr != 0x2A:
            return super().writeto(addr, data, stop)
        self.tiny_pointer = data[0]
        for offset, value in enumerate(data[1:]):
            self.tiny[self.tiny_pointer + offset] = value

    def readfrom(self, addr, nbytes):
        if addr != 0x2A:
            return super().readfrom(addr, nbytes)
        return bytes(self.tiny.get(self.tiny_pointer + i, 0) for i in range(nbytes))


class FakeTwiboot:
    """Models twiboot, including its vector patching during a flash."""

    PAGE = 64
    APP_SIZE = 0x1C00

    def __init__(self, in_app=False):
        self.flash = bytearray(b"\xff" * self.APP_SIZE)
        self.pointer = 0
        self.mode = None
        self.in_app = in_app
        self.page_order = []
        self.app_started = False
        self.corrupt_reads = False

    def scan(self):
        return [0x2A] if self.in_app else [0x29]

    def writeto(self, addr, data, stop=True):
        if addr == 0x2A:
            assert bytes(data) == b"\x7f\xb0"
            self.in_app = False
            return
        assert addr == 0x29 and not self.in_app
        if bytes(data[:2]) == b"\x01\x80":
            self.app_started = True
            self.in_app = True
            raise OSError(19)  # twiboot NACKs this command's last byte
        elif data[0] == 0x01:
            self.mode = "version"
        elif bytes(data[:4]) == b"\x02\x00\x00\x00":
            self.mode = "chip"
        elif bytes(data[:2]) == b"\x02\x01":
            self.mode = "flash"
            self.pointer = (data[2] << 8) | data[3]
            if len(data) > 4:
                assert len(data) == 4 + self.PAGE
                assert self.pointer % self.PAGE == 0
                self.flash[self.pointer : self.pointer + self.PAGE] = data[4:]
                self.page_order.append(self.pointer)
                raise OSError(19)  # twiboot NACKs the last byte of a page

    def readfrom(self, addr, nbytes):
        if self.mode == "version":
            return b"TWIBOOT v3.2\x00\x00\x00\x00"[:nbytes]
        if self.mode == "chip":
            return b"\x1e\x93\x0b\x40\x1c\x00\x02\x00"[:nbytes]
        data = bytes(self.flash[self.pointer : self.pointer + nbytes])
        if self.corrupt_reads and self.pointer == 0x40:
            return b"\x00" + data[1:]
        return data


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


class TinyTests(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBoard()
        self.rocket = rs.Rocket(1, i2c=self.bus, adc=FakeAdc(1_000_000))

    def test_init_finds_tiny_and_claims_host(self):
        self.rocket.init()
        self.assertEqual(self.rocket.tiny_version, 7)
        self.assertEqual(self.bus.tiny[0x30], 1)

    def test_light_prefers_tiny(self):
        self.rocket.init()
        self.assertEqual(self.rocket.light_mv(), 511 * 3300 // 1023)

    def test_light_falls_back_to_adc(self):
        self.bus.scan = lambda: [0x50]
        self.rocket.init()
        self.assertIsNone(self.rocket.tiny_version)
        self.assertEqual(self.rocket.light_mv(), 1000)

    def test_wrong_device_is_not_trusted(self):
        self.bus.tiny[0x00] = 0x11
        self.rocket.init()
        self.assertIsNone(self.rocket.tiny_version)

    def test_set_tiny_led_writes_all_three_registers(self):
        self.rocket.set_tiny_led(rs.TINY_LED_PWM, 128, 25)
        self.assertEqual([self.bus.tiny[r] for r in (0x20, 0x21, 0x22)], [2, 128, 25])


class FlashTests(unittest.TestCase):
    def test_flash_pads_writes_page_zero_last_and_starts_app(self):
        boot = FakeTwiboot()
        image = bytes(range(200))
        tf.flash(boot, image)
        self.assertEqual(boot.page_order, [0xC0, 0x80, 0x40, 0x00])
        self.assertEqual(bytes(boot.flash[:200]), image)
        self.assertEqual(bytes(boot.flash[200:256]), b"\xff" * 56)
        self.assertTrue(boot.app_started)

    def test_flash_moves_a_running_app_into_the_bootloader(self):
        boot = FakeTwiboot(in_app=True)
        tf.flash(boot, b"\x01" * 64)
        self.assertEqual(boot.page_order, [0])

    def test_failed_verify_does_not_start_app(self):
        boot = FakeTwiboot()
        boot.corrupt_reads = True
        with self.assertRaises(tf.FlashError):
            tf.flash(boot, b"\x55" * 128)
        self.assertFalse(boot.app_started)

    def test_app_that_never_answers_is_an_error(self):
        boot = FakeTwiboot()
        boot.scan = lambda: [0x29]
        with self.assertRaises(tf.FlashError):
            tf.flash(boot, b"\x55" * 64)

    def test_page_that_never_landed_fails_verify(self):
        boot = FakeTwiboot()
        real_writeto = boot.writeto

        def drop_writes(addr, data, stop=True):
            if len(data) > 4:
                raise OSError(19)
            real_writeto(addr, data, stop)

        boot.writeto = drop_writes
        with self.assertRaises(tf.FlashError):
            tf.flash(boot, b"\x55" * 64)
        self.assertFalse(boot.app_started)

    def test_rejects_oversized_image_before_writing(self):
        boot = FakeTwiboot()
        with self.assertRaises(tf.FlashError):
            tf.flash(boot, b"\x00" * (0x1C00 + 1))
        self.assertEqual(boot.page_order, [])

    def test_rejects_empty_image(self):
        boot = FakeTwiboot()
        with self.assertRaises(tf.FlashError):
            tf.flash(boot, b"")
        self.assertEqual(boot.page_order, [])

    def test_progress_ends_at_one(self):
        seen = []
        tf.flash(FakeTwiboot(), b"\x00" * 128, seen.append)
        self.assertEqual(seen[-1], 1)


if __name__ == "__main__":
    unittest.main()
