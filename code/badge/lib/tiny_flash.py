"""Update the rocket's ATtiny from the badge through the twiboot bootloader."""

import time

BOOT_ADDR = 0x29
APP_ADDR = 0x2A

REG_COMMAND = 0x7F
CMD_BOOTLOADER = 0xB0

CHIP_SIGNATURE = b"\x1e\x93\x0b"  # ATtiny85
BOOTLOADER_ID = b"TWIBOOT"

_CMD_WAIT = b"\x00"
_CMD_VERSION = b"\x01"
_CMD_START_APP = b"\x01\x80"
_CMD_CHIPINFO = b"\x02\x00\x00\x00"
_CMD_FLASH = b"\x02\x01"

_ENTER_TIMEOUT_MS = 2000
_POLL_MS = 10


class FlashError(Exception):
    pass


def _flash_command(addr: int) -> bytes:
    return _CMD_FLASH + bytes((addr >> 8, addr & 0xFF))


def enter_bootloader(i2c) -> None:
    """Hold the ATtiny in twiboot, asking the app to switch to it if needed."""
    deadline = time.ticks_add(time.ticks_ms(), _ENTER_TIMEOUT_MS)
    asked = False
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        found = i2c.scan()
        if BOOT_ADDR in found:
            # Stops twiboot's countdown, so it stays until told to start the app
            i2c.writeto(BOOT_ADDR, _CMD_WAIT)
            return
        if APP_ADDR in found and not asked:
            i2c.writeto(APP_ADDR, bytes((REG_COMMAND, CMD_BOOTLOADER)))
            asked = True
        time.sleep_ms(_POLL_MS)
    raise FlashError("bootloader not found")


def chip_info(i2c):
    """Check the bootloader and return (page size, application size)."""
    i2c.writeto(BOOT_ADDR, _CMD_VERSION, False)
    version = i2c.readfrom(BOOT_ADDR, 16)
    if not version.startswith(BOOTLOADER_ID):
        raise FlashError("unexpected bootloader")
    i2c.writeto(BOOT_ADDR, _CMD_CHIPINFO, False)
    info = i2c.readfrom(BOOT_ADDR, 8)
    if info[:3] != CHIP_SIGNATURE:
        raise FlashError("unexpected chip")
    return info[3], (info[4] << 8) | info[5]


def _write_page(i2c, addr: int, page: bytes) -> None:
    # twiboot NACKs the last byte of a full page, which raises OSError here even
    # on success. flash() reads every page back, which catches a real failure.
    try:
        i2c.writeto(BOOT_ADDR, _flash_command(addr) + page)
    except OSError:
        pass


def _read_page(i2c, addr: int, size: int) -> bytes:
    i2c.writeto(BOOT_ADDR, _flash_command(addr), False)
    return i2c.readfrom(BOOT_ADDR, size)


def start_app(i2c) -> None:
    """Start the application and wait for it to answer."""
    # twiboot NACKs this command's last byte too, so success is judged by the
    # application appearing on the bus.
    try:
        i2c.writeto(BOOT_ADDR, _CMD_START_APP)
    except OSError:
        pass
    deadline = time.ticks_add(time.ticks_ms(), _ENTER_TIMEOUT_MS)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if APP_ADDR in i2c.scan():
            return
        time.sleep_ms(_POLL_MS)
    raise FlashError("application did not start")


def flash(i2c, image: bytes, progress=None) -> None:
    """Write and verify an application image, then start it.

    Pages are written from the top down with page 0 last. Page 0 holds the jump
    into twiboot, so the chip can still reach the bootloader if this is
    interrupted, apart from the few ms that page 0 itself is being rewritten.

    On any failure the chip stays in twiboot, so this can simply be run again.
    progress, if given, is called with the fraction completed.
    """
    enter_bootloader(i2c)
    page_size, app_size = chip_info(i2c)
    if not 0 < len(image) <= app_size:
        raise FlashError("image size %d doesn't fit" % len(image))

    padded = bytearray(image)
    padded.extend(b"\xff" * (-len(padded) % page_size))
    addrs = list(range(0, len(padded), page_size))

    done = 0
    for addr in reversed(addrs):
        _write_page(i2c, addr, bytes(padded[addr : addr + page_size]))
        done += 1
        if progress:
            progress(done / (2 * len(addrs)))

    for addr in addrs:
        page = bytes(padded[addr : addr + page_size])
        if _read_page(i2c, addr, page_size) != page:
            raise FlashError("verify failed at 0x%04x" % addr)
        done += 1
        if progress:
            progress(done / (2 * len(addrs)))

    start_app(i2c)


def flash_file(i2c, path: str, progress=None) -> None:
    with open(path, "rb") as image_file:
        flash(i2c, image_file.read(), progress)
