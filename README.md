# rocket_sao_badge

A rocket-shaped **SAO** (an add-on board for conference badges) with LEDs, an
ambient light sensor and a small microcontroller. This repo has the PCB, the
firmware that runs on the rocket, and the code that lets the **2026 Hackaday
Supercon "Billboard" badge** control it.

If you have never heard of an SAO or the Billboard badge, start at
[Background](#background). If you have a rocket in hand and just want it
working, skip to [Quick start](#quick-start).

---

## Contents

- [Background](#background)
  - [What is a conference badge?](#what-is-a-conference-badge)
  - [What is an SAO?](#what-is-an-sao)
  - [What is I2C?](#what-is-i2c)
  - [The Billboard badge](#the-billboard-badge)
- [The rocket SAO hardware](#the-rocket-sao-hardware)
- [How the rocket and badge talk](#how-the-rocket-and-badge-talk)
- [Quick start](#quick-start)
- [Using the rocket from badge code](#using-the-rocket-from-badge-code)
- [ATtiny register map](#attiny-register-map)
- [Updating the rocket's firmware from the badge](#updating-the-rockets-firmware-from-the-badge)
- [Programming a blank rocket (first-time setup)](#programming-a-blank-rocket-first-time-setup)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Repository layout](#repository-layout)

---

## Background

### What is a conference badge?

At hacker and electronics conferences (DEF CON, Hackaday Supercon and others),
your entry badge is often a working circuit board: a small computer with a
screen, LEDs and buttons that you wear on a lanyard. People write software for
it, solder things to it and swap add-ons with each other.

### What is an SAO?

**SAO** stands for "Simple Add-On" (originally "Shitty Add-On"). It is a small
decorative PCB that plugs into a standard 6-pin socket on a badge. The badge
supplies power, and the add-on can do as little as light an LED, or as much as
talk to the badge over a data bus.

The standard SAO connector is a 2×3 header with 2.54 mm (0.1") spacing:

```
        ┌─────────┬─────────┐
        │ 1  VCC  │ 2  GND  │      VCC is 3.3 V
        ├─────────┼─────────┤
        │ 3  SDA  │ 4  SCL  │      I2C data and clock
        ├─────────┼─────────┤
        │ 5 GPIO1 │ 6 GPIO2 │      two general-purpose pins
        └─────────┴─────────┘
```

- **VCC / GND** power the add-on (3.3 V on this badge).
- **SDA / SCL** are an I2C bus (see below). Every SAO socket on a badge
  usually shares the *same* I2C bus.
- **GPIO1 / GPIO2** are plain pins wired to the badge's microcontroller. Each
  socket has its own pair, and the badge can use them as digital or analog
  inputs or outputs.

### What is I2C?

**I2C** ("eye-squared-see") is a two-wire bus that lets one *controller* (here,
the badge) talk to many *targets* (chips on the add-ons) over the same two
wires:

- **SCL** is the clock, driven by the controller.
- **SDA** is the data line, used by both sides in turn.

Every target has a 7-bit **address** (written in hex, like `0x50`). The
controller starts each transfer by sending an address, and only the chip with
that address answers. Most chips work like a small bank of numbered
**registers**: you write a register number, then read or write the bytes
stored there.

Both lines are "open drain": any device can pull them low, and resistors pull
them back up to 3.3 V. This matters for troubleshooting. **If any one device on
the bus holds SCL or SDA low, the whole bus stops working for everyone.**

### The Billboard badge

The 2026 Hackaday Supercon badge is the "Billboard" badge:

- An **ESP32-S3** microcontroller (with WiFi and Bluetooth) running
  **MicroPython**, so badge software is plain Python files on the badge's flash.
- A large 9.7" black/white/red **e-paper** display. E-paper keeps its image with
  no power but takes a while to redraw, so apps update it rarely.
- A row of RGB LEDs, four buttons (Menu +/- and User A/B), and **three SAO
  sockets**.
- An **app switcher**: every Python file in `/apps` on the badge becomes an app
  you can switch to with the menu buttons.

The badge's SAO wiring:

| Socket | SAO GPIO1 (pin 5) | SAO GPIO2 (pin 6) |
|---|---|---|
| SAO1 | GPIO2 | GPIO42 |
| SAO2 | GPIO4 | GPIO5 |
| SAO3 | GPIO7 | GPIO6 |
| all  | I2C SDA = GPIO17 | I2C SCL = GPIO18 |

All three sockets share one I2C bus (MicroPython I2C bus 0, 100 kHz in this
code).

---

## The rocket SAO hardware

The design lives in `pcb/` (KiCad). The board is named
`sao_light_coms` ("light communications"): it can both emit and sense light.

### Main parts

| Part | What it is | What it does on the rocket |
|---|---|---|
| **U1** ATtiny85 | A tiny 8-pin microcontroller (8 KB flash, 512 B RAM, 512 B EEPROM) | The rocket's own brain. Filters the light sensor, runs the extra LED, stores settings, and answers the badge on I2C. |
| **U3** TI LP5810 | A 4-channel I2C LED driver | Drives four LEDs with a precise current, and can play breathing/chasing animations *by itself* once loaded. |
| **A1** ALS-PT19 | Ambient light sensor (a phototransistor tuned to human vision) | Turns light into a current. R1 (56 kΩ) turns it into a voltage and C1 (10 µF) smooths it (about 0.56 s time constant). |
| **Q1** BC818 | NPN transistor | Lets an ATtiny pin drive LED D1 with more current than the pin can supply. |
| **J3** | SAO 2×3 header | Plugs into the badge. |
| **J1** | 5-pin JST-PH | Programming header (AVR ISP) for the ATtiny. |

LEDs D4–D7 are on the LP5810's four channels, and D1 is on Q1. The board has
footprints for extra through-hole LEDs (D2, D3, D8–D11), an optional op-amp
light amplifier (U2), a button (SW1) and I2C pull-ups (R7/R8). Those are not
fitted by default; the badge already provides I2C pull-ups.

### How the parts are wired

```
                        Badge SAO socket (J3)
     VCC ─ GND ─ SDA ───────────── SCL ───────────── GPIO1 ────── GPIO2
                  │                 │                  │            │
                  ├── LP5810 SDA    ├── LP5810 SCL     │            │
                  │   (LEDs D4-D7)  │                  │            │
                  │                 │                  │            │
                  └── ATtiny PB0    └── ATtiny PB2     │            │
                                                       │            │
     light sensor ── R1/C1 ── "SENSE" ─────────────────┴─ ATtiny PB3 (ADC)
                                                                    │
                                 ATtiny PB1 ────────────────────────┴─ Q1 ── LED D1
```

| ATtiny85 pin | Port | Net | Connected to |
|---|---|---|---|
| 1 | PB5 | RESET | J1 programming header only |
| 2 | PB3 | SENSE | Light sensor, and SAO GPIO1 |
| 3 | PB4 | BUTTON | Optional button (not fitted) |
| 4 | – | GND | |
| 5 | PB0 | SDA | SAO I2C, LP5810 |
| 6 | PB1 | LED | Q1 (LED D1), and SAO GPIO2 |
| 7 | PB2 | SCL | SAO I2C, LP5810 |
| 8 | – | VCC | 3.3 V from the badge |

Two consequences of this wiring:

1. **The badge and the ATtiny share the light sensor.** The badge can read the
   sensor voltage directly through GPIO1, *or* ask the ATtiny for its filtered
   reading over I2C.
2. **The ATtiny drives GPIO2 as an output.** The badge must **never** drive
   GPIO2 (GPIO42 on SAO1), or the two chips will fight over the pin.

---

## How the rocket and badge talk

On the I2C bus, one rocket shows up at several addresses:

| Address | Chip | When |
|---|---|---|
| `0x50`–`0x53` | LP5810 LED driver | Always. The LP5810 has more than 256 registers, so it uses the low two bits of its address as the top bits of the register number. One chip answers on four addresses. |
| `0x2A` | ATtiny, running `rocket_fw` | Normal operation |
| `0x29` | ATtiny, running the **twiboot** bootloader | Only while its firmware is being updated, or for about a second after power-up |

The design splits the work:

- **The badge is in charge.** It talks to the LP5810 directly to set
  brightness and load animations. Once loaded, an animation runs on the LP5810
  with no further help from the badge.
- **The ATtiny is a "smart peripheral"** for jobs that need steady timing next
  to the hardware: it averages the light sensor, counts light changes, runs LED
  D1 (on, PWM dimming, or blinking), and offers 512 bytes of EEPROM that keeps
  data when unplugged.
- **Standalone mode.** If nobody talks to the ATtiny within about 5 seconds of
  power-up (say, on a badge that doesn't know about the rocket), it briefly
  takes over the I2C bus, starts a breathing animation on the LP5810, and then
  goes back to listening. So the rocket glows on any badge. The badge driver
  writes the "host present" register as soon as it finds the rocket, which
  prevents this.
- **Firmware updates over I2C.** The ATtiny runs a small bootloader
  ([twiboot](https://github.com/orempel/twiboot)) that can rewrite its program
  over the same I2C bus. The badge carries a copy of the rocket firmware and
  can update the rocket while it is plugged in. No programmer is needed.

---

## Quick start

You need:

- A Billboard badge running its stock MicroPython firmware.
- A rocket SAO that has already been programmed (see
  [first-time setup](#programming-a-blank-rocket-first-time-setup) if not).
- A computer with a USB-C cable and
  [`mpremote`](https://docs.micropython.org/en/latest/reference/mpremote.html)
  (`pip install mpremote`).

1. **Plug the rocket into SAO1**, with the badge off. Line up pin 1 (VCC) on
   both, and press it fully into the socket. A half-seated SAO causes flaky
   I2C.
2. **Copy the badge files** from `code/badge/` onto the badge, keeping the same
   folders:

   ```sh
   cd code/badge
   mpremote cp lib/rocket_sao.py :lib/rocket_sao.py
   mpremote cp lib/tiny_flash.py :lib/tiny_flash.py
   mpremote mkdir :data          # skip if it already exists
   mpremote cp data/rocket_fw.bin :data/rocket_fw.bin
   mpremote cp apps/rocket.py :apps/rocket.py
   ```

3. **Reset the badge** (`mpremote reset`, or the reset button), and watch the
   serial log with `mpremote` to make sure it boots. The badge imports every
   app at startup, so a broken file in `/apps` stops the whole badge from
   booting.
4. **Open the Rocket app** with the menu buttons.
   - The rocket starts its first animation.
   - **User A** steps through the animations: `breathe`, `chase`, `swap`,
     `launch`.
   - **User B** toggles "follow light": the rocket dims in the dark and
     brightens in bright light.
   - The badge's LED bar shows the light level in green. A single red LED means
     the badge can't find the rocket.

If your rocket is in SAO2 or SAO3, change `ROCKET_PORT` at the top of
`apps/rocket.py`.

---

## Using the rocket from badge code

`lib/rocket_sao.py` is the driver. From your own app or from the badge's REPL
(`mpremote repl`):

```python
from lib.rocket_sao import Rocket, TINY_LED_BLINK

r = Rocket(port=1)     # the SAO socket it's plugged into
r.present()            # True if the LP5810 answers
r.init()               # all LEDs off, manual mode; also finds the ATtiny

r.set_led(0, 255)      # LED 0 fully on (0-255)
r.set_all(40)          # all four LEDs dim
r.set_current(100)     # LED current, 0-255 is 0-25.5 mA

r.animate("chase")     # runs on the LP5810 until stopped
r.stop()

r.light_mv()           # sensor voltage in mV
r.light_level()        # light as 0-255

r.tiny_version         # rocket_fw version, or None if the ATtiny isn't there
r.set_tiny_led(TINY_LED_BLINK, half_period=25)   # LED D1 blinks every 0.25 s
```

Notes:

- `set_led()` and `set_all()` stop any running animation.
- `light_mv()` uses the ATtiny's filtered reading when it is running, and falls
  back to reading the sensor through the badge's own ADC on GPIO1 otherwise.
  Either way the sensor reacts slowly (about half a second) because of C1.
- Dim indoor light reads only about 100–300 mV. That is normal.
- You can add animations to `PATTERNS` in `rocket_sao.py`. Each LED gets five
  brightness points (PWM1–PWM5) and a slope-time code. See the LP5810 data
  sheet (TI SNVSCD0) and register map (SNVU926).

---

## ATtiny register map

`rocket_fw` (in `code/rocket_fw/rocket_fw.ino`) acts like a register-based I2C
chip at address `0x2A`. Write a register number to choose where to start, then
read or write bytes. The register number increases by one for each byte.

| Reg | Access | Meaning |
|---|---|---|
| `0x00` | R | ID, always `'R'` (`0x52`) |
| `0x01` | R | Firmware version |
| `0x02` | R | Capabilities: bit 0 light, bit 1 LED, bit 2 EEPROM, bit 3 bootloader |
| `0x03` | R | Status: bit 0 host seen, bit 1 standalone animation ran, bit 2 EEPROM busy |
| `0x10` `0x11` | R | Filtered light, 0–1023 (low byte, high byte). 0 is 0 V and 1023 is VCC |
| `0x12` | R/W | Lowest light / 4 since reset. Writing anything resets the min and max |
| `0x13` | R | Highest light / 4 since reset |
| `0x14` | R/W | How big a light change counts as an "event" (default 16) |
| `0x15` | R | Light event counter (wraps at 255) |
| `0x20` | R/W | LED D1 mode: 0 off, 1 on, 2 PWM, 3 blink |
| `0x21` | R/W | LED D1 PWM duty, 0–255 |
| `0x22` | R/W | LED D1 blink half-period, in 10 ms steps |
| `0x30` | R/W | Host present. Non-zero stops standalone mode |
| `0x40` `0x41` | R/W | EEPROM address (0–511), low byte then high byte |
| `0x42` | R/W | EEPROM data at that address; the address then moves on by one. Use one byte per transfer, and after a write wait for status bit 2 to clear |
| `0x7F` | W | Write `0xB0` to jump into the twiboot bootloader |

Example, reading the light level by hand from the REPL:

```python
r.i2c.writeto(0x2A, b"\x10", False)
lo, hi = r.i2c.readfrom(0x2A, 2)
print(lo | hi << 8)
```

---

## Updating the rocket's firmware from the badge

The ATtiny's flash memory is split in two:

- **twiboot**, the bootloader, lives in the top 1 KB (from `0x1C00`) and is
  never overwritten.
- **rocket_fw**, the application, fills the rest.

At power-up twiboot listens on `0x29` for about a second. If nobody talks to
it, it starts rocket_fw, which then answers on `0x2A`. rocket_fw can also jump
back into twiboot when the badge writes `0xB0` to register `0x7F`.

`lib/tiny_flash.py` handles the whole update from the badge:

```python
from lib.rocket_sao import Rocket
from lib import tiny_flash

r = Rocket(1)
tiny_flash.flash_file(r.i2c, "/data/rocket_fw.bin",
                      progress=lambda f: print("%d%%" % (f * 100)))
```

It:

1. finds the ATtiny, asks it to enter twiboot, and tells twiboot to stay put;
2. checks it is really twiboot on an ATtiny85;
3. writes the image a page (64 bytes) at a time, from the top down, writing
   page 0 last;
4. reads every page back to verify it;
5. starts the new firmware and waits for it to appear on `0x2A`.

This takes about 1.2 seconds. If it fails partway, the ATtiny stays in twiboot,
so you can run it again. Page 0 is written last because it holds the jump into
twiboot. That keeps an interrupted update recoverable, except during the few
milliseconds while page 0 itself is being written.

You will see an `OSError` swallowed during each page write. That is expected:
twiboot deliberately refuses the last byte of each page, and the read-back
check catches real failures.

### Building a new rocket_fw image

1. Open `code/rocket_fw/rocket_fw.ino` in the Arduino IDE with an ATtiny85 core
   that provides `Wire` for the ATtiny's USI hardware (for example
   ATTinyCore), set to ATtiny85 at 8 MHz internal clock.
2. Export the compiled binary, then convert the `.hex` (or `.elf`) to a raw
   binary, for example `avr-objcopy -I ihex -O binary rocket_fw.hex
   rocket_fw.bin`.
3. Bump `FW_VERSION` so you can tell the versions apart, copy the `.bin` to
   `/data/rocket_fw.bin` on the badge, and flash it as above.

The image must fit below `0x1C00` (7 KB).

---

## Programming a blank rocket (first-time setup)

A freshly assembled rocket has an empty ATtiny. It needs twiboot and the right
fuse settings once, using an AVR ISP programmer (for example an Arduino Uno
running the "ArduinoISP" sketch) connected to **J1**:

| J1 pin | Signal | ISP name |
|---|---|---|
| 1 | SDA / PB0 | MOSI |
| 2 | LED / PB1 | MISO |
| 3 | SCL / PB2 | SCK |
| 4 | RESET / PB5 | RESET |
| 5 | GND | GND |

> **Warning: take the rocket off the badge first.** An Uno's ISP lines are 5 V,
> and on the badge they would reach the ESP32's 3.3 V pins. J1 has no VCC pin,
> so power the rocket from the programmer separately (SAO pin 1 is VCC).

Then, with `avrdude`:

```sh
avrdude -c stk500v1 -P /dev/ttyACM0 -b 19200 -p t85 \
  -U lfuse:w:0xE2:m -U hfuse:w:0xD5:m -U efuse:w:0xFE:m \
  -U flash:w:code/twiboot/twiboot_rocket.hex:i
```

- `lfuse 0xE2`: 8 MHz internal clock.
- `hfuse 0xD5`: keep EEPROM through chip erase, and turn on brown-out detection.
- `efuse 0xFE`: enable self-programming, which twiboot needs.

Put the rocket back on the badge and run `tiny_flash.flash_file(...)` as above
to install rocket_fw. From then on, all updates go over I2C.

### About the twiboot patch

`code/twiboot/twiboot_rocket.hex` is twiboot v3.2 built for the ATtiny85 with
`code/twiboot/rocket.patch` applied. The patch changes three things that matter
on this board:

- **LED support is off.** Stock twiboot blinks a status LED on pins that here
  are the button and RESET lines.
- **SDA and SCL are released before starting the app**, so twiboot doesn't
  hold the shared bus.
- **The jump into the app uses a word address.** The ATtiny85 has no hardware
  boot section, so twiboot fakes one and jumps to the app itself. Stock code
  used a byte address there, so the app never started.

---

## Tests

`code/badge/tests/test_rocket_sao.py` runs on your computer, not on the badge.
It checks the driver and the flashing code against simulated LP5810, ATtiny and
twiboot chips:

```sh
python3 code/badge/tests/test_rocket_sao.py
```

`code/test_firmware/` is an older bring-up sketch that drives the LP5810 from
the ATtiny and blinks values out on LED D1. You don't need it for normal use.

---

## Troubleshooting

**The badge doesn't find the rocket (red LED in the Rocket app, empty I2C
scan).**

- **Reseat the rocket.** A partly inserted SAO is the most common cause of
  writes failing partway and the bus locking up.
- **Unplug every other SAO.** All sockets share one I2C bus, and some SAOs (for
  example other ATtiny85 boards that use those pins as plain GPIO) hold SCL or
  SDA low. That kills the bus for the rocket too.
- Check the line levels. From the REPL, read GPIO17 (SDA) and GPIO18 (SCL) as
  inputs. Both should read high when idle. If SCL is stuck low, power-cycle the
  badge.

**The badge doesn't boot after copying files.**
An error while importing any file in `/apps` stops the boot. Connect with
`mpremote`, look at the error in the serial log, then fix or delete the file.
Note that the badge's `lib/sao.py` can't be imported on the shipped MicroPython
build, which is why `rocket_sao.py` defines its own pins.

**The light reading seems low.**
Indoor light gives only a few hundred mV. Shine a phone torch on the sensor to
check the range. The reading takes about half a second to settle.

**The rocket breathes on its own.**
That's standalone mode. It means nothing on the badge talked to the rocket
within 5 seconds of power-up. Opening the Rocket app takes over.

**Firmware update fails with "bootloader not found".**
Power-cycle the badge and try again right away: twiboot is also reachable for
about a second after every power-up.

---

## Repository layout

```
code/
  badge/                  Files to copy onto the Billboard badge
    apps/rocket.py          The Rocket app (animations + light meter)
    lib/rocket_sao.py       Driver: LP5810, light sensor, ATtiny registers
    lib/tiny_flash.py       Updates the ATtiny over I2C via twiboot
    data/rocket_fw.bin      Prebuilt rocket firmware image
    tests/                  Host-side tests with simulated chips
  rocket_fw/rocket_fw.ino   ATtiny85 firmware (I2C target at 0x2A)
  twiboot/                  twiboot patch and prebuilt bootloader hex
  test_firmware/            Early standalone bring-up sketch
pcb/                      KiCad schematic, PCB and BOM
```

## License

See [LICENSE](LICENSE).
