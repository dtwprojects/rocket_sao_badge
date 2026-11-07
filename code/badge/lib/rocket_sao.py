"""Driver for the rocket SAO on the Billboard badge.

The badge talks to the rocket's LP5810 LED driver directly over the shared
SAO I2C bus and reads the ambient light sensor through the port's GPIO1 pin.

Never drive the port's GPIO2 pin from the badge. It is wired to ATtiny PB1,
which the ATtiny firmware drives as an output.

Register details come from TI SNVSCD0 (data sheet) and SNVU926 (register map).
"""

import machine
import time

# Pins are defined here because lib/sao.py can't be imported on the shipped
# firmware: its "/" parameter syntax is a SyntaxError on this MicroPython, and
# an import failure in an app stops the whole badge from booting.
I2C_BUS = 0
I2C_SCL = 18
I2C_SDA = 17
I2C_FREQ = 100_000

# The LP5810 keeps register bits 9:8 in the low bits of its I2C address, so one
# chip answers on 0x50-0x53: use lp_addr() rather than this constant directly.
LP_BASE_ADDR = 0x50

REG_CHIP_EN = 0x000
REG_MAX_CURRENT = 0x001
REG_AUTO_EN = 0x004
REG_EXP_EN = 0x006
REG_DEV_CONFIG_12 = 0x00D
REG_UPDATE = 0x010
REG_START = 0x011
REG_STOP = 0x012
REG_LED_EN = 0x020
REG_FAULT_CLEAR = 0x022
REG_MANUAL_DC = 0x030
REG_MANUAL_PWM = 0x040
REG_AUTO_DC = 0x050
REG_AEP = 0x080
REG_STATUS = 0x300

CMD_UPDATE = 0x55
CMD_START = 0xFF
CMD_STOP = 0xAA

NUM_LEDS = 4
ALL_LEDS = 0x0F
AEP_SIZE = 26  # Bytes of animation registers per LED
DEFAULT_DC = 0xBF  # About 19 mA, matching the test firmware
LSD_THRESHOLD_CONFIG = 0x0B  # Data sheet recommended Dev_Config_12 value

CONFIG_ERR = 0x01
TSD_FAULT = 0x02

_ADC_SAMPLES = 16
_FULL_SCALE_MV = 3100

_PORT_SENSE_PINS = {1: 2, 2: 4, 3: 7}  # GPIO numbers of each port's SAO GPIO1


def lp_addr(reg: int) -> int:
    """I2C address for an LP5810 register."""
    return LP_BASE_ADDR | (reg >> 8)


def _aep(pwm, t_code: int) -> bytes:
    """One LED's animation: looping AEU1 only, four equal slopes.

    pwm holds PWM1-PWM5 and t_code is the 4-bit slope time (see Table 7-3).
    """
    times = (t_code << 4) | t_code
    regs = bytearray(AEP_SIZE)
    regs[0] = 0x00  # No pause at the start or end
    regs[1] = 0x0F  # Use AEU1 only, repeat the pattern forever
    regs[2:7] = bytes(pwm)
    regs[7] = times  # T2 | T1
    regs[8] = times  # T4 | T3
    regs[9] = 0x01  # Play AEU1 once per pattern
    return bytes(regs)


# Each pattern lists PWM1-PWM5 per LED. First and last values of a loop match
# so that it doesn't flicker on the wrap, per the data sheet.
PATTERNS = {
    "breathe": (0x6, ((0, 128, 255, 128, 0),) * 4),
    "chase": (
        0x2,
        (
            (255, 0, 0, 0, 255),
            (0, 255, 0, 0, 0),
            (0, 0, 255, 0, 0),
            (0, 0, 0, 255, 0),
        ),
    ),
    "swap": (
        0x4,
        (
            (0, 255, 0, 255, 0),
            (255, 0, 255, 0, 255),
            (0, 255, 0, 255, 0),
            (255, 0, 255, 0, 255),
        ),
    ),
    "launch": (0x5, ((0, 32, 96, 255, 0),) * 4),
}
PATTERN_NAMES = ("breathe", "chase", "swap", "launch")


class RocketError(Exception):
    pass


class Rocket:
    def __init__(self, port: int = 1, i2c=None, adc=None) -> None:
        if port not in _PORT_SENSE_PINS:
            raise ValueError("port must be 1, 2 or 3")
        self.port = port
        self.i2c = i2c or machine.I2C(
            I2C_BUS, scl=I2C_SCL, sda=I2C_SDA, freq=I2C_FREQ
        )
        self.adc = adc or machine.ADC(
            machine.Pin(_PORT_SENSE_PINS[port]), atten=machine.ADC.ATTN_11DB
        )
        self.animating = False
        self.dc = DEFAULT_DC

    def lp_write(self, reg: int, data) -> None:
        """Write one byte, or several consecutive registers."""
        if isinstance(data, int):
            data = bytes((data,))
        self.i2c.writeto(lp_addr(reg), bytes((reg & 0xFF,)) + bytes(data))

    def lp_read(self, reg: int, nbytes: int = 1) -> bytes:
        addr = lp_addr(reg)
        self.i2c.writeto(addr, bytes((reg & 0xFF,)), False)
        return self.i2c.readfrom(addr, nbytes)

    def present(self) -> bool:
        return LP_BASE_ADDR in self.i2c.scan()

    def status(self) -> int:
        return self.lp_read(REG_STATUS)[0]

    def init(self) -> None:
        """Put the LP5810 in a known state: manual mode with all LEDs off."""
        time.sleep_ms(1)
        self.lp_write(REG_CHIP_EN, 0x01)
        self.lp_write(REG_STOP, CMD_STOP)
        self.lp_write(REG_MAX_CURRENT, 0x00)
        self.lp_write(REG_DEV_CONFIG_12, LSD_THRESHOLD_CONFIG)
        self._use_manual()
        self.lp_write(REG_MANUAL_DC, bytes((self.dc,)) * NUM_LEDS)
        self.lp_write(REG_MANUAL_PWM, bytes(NUM_LEDS))

        status = self.status()
        if status & (CONFIG_ERR | TSD_FAULT):
            raise RocketError("LP5810 status 0x%02x" % status)

    def _use_manual(self) -> None:
        self.lp_write(REG_AUTO_EN, 0x00)
        self.lp_write(REG_EXP_EN, 0x00)
        self.lp_write(REG_UPDATE, CMD_UPDATE)
        self.lp_write(REG_LED_EN, ALL_LEDS)
        self.animating = False

    def stop(self) -> None:
        """End any animation and return to manual mode."""
        self.lp_write(REG_STOP, CMD_STOP)
        self._use_manual()

    def set_led(self, led: int, value: int) -> None:
        """Set one LED's brightness, 0-255. Ends any running animation."""
        if not 0 <= led < NUM_LEDS:
            raise ValueError("led must be 0-3")
        if self.animating:
            self.stop()
        self.lp_write(REG_MANUAL_PWM + led, value)

    def set_all(self, value: int) -> None:
        """Set all LEDs' brightness, 0-255. Ends any running animation."""
        if self.animating:
            self.stop()
        self.lp_write(REG_MANUAL_PWM, bytes((value,)) * NUM_LEDS)

    def set_current(self, dc: int) -> None:
        """Set LED current, 0-255 (0-25.5 mA), for manual and animated output."""
        self.dc = dc
        levels = bytes((dc,)) * NUM_LEDS
        self.lp_write(REG_MANUAL_DC, levels)
        self.lp_write(REG_AUTO_DC, levels)

    def animate(self, pattern: str) -> None:
        """Start a pattern from PATTERNS.

        It runs on the LP5810 itself, so it continues without the badge.
        """
        t_code, pwms = PATTERNS[pattern]
        self.lp_write(REG_STOP, CMD_STOP)
        self.lp_write(REG_AUTO_EN, ALL_LEDS)
        self.lp_write(REG_EXP_EN, ALL_LEDS)
        self.lp_write(REG_UPDATE, CMD_UPDATE)
        self.lp_write(REG_LED_EN, ALL_LEDS)
        self.lp_write(REG_AUTO_DC, bytes((self.dc,)) * NUM_LEDS)
        for led in range(NUM_LEDS):
            self.lp_write(REG_AEP + led * AEP_SIZE, _aep(pwms[led], t_code))
        self.lp_write(REG_START, CMD_START)
        self.animating = True

        status = self.status()
        if status & (CONFIG_ERR | TSD_FAULT):
            raise RocketError("LP5810 status 0x%02x" % status)

    def light_mv(self) -> int:
        """Ambient light sensor voltage in mV, averaged over a short burst.

        The sensor is filtered by R1/C1 (about 0.56 s), so it responds slowly.
        """
        total = 0
        for _ in range(_ADC_SAMPLES):
            total += self.adc.read_uv()
        return total // (_ADC_SAMPLES * 1000)

    def light_level(self) -> int:
        """Ambient light as 0-255."""
        return min(self.light_mv() * 255 // _FULL_SCALE_MV, 255)
