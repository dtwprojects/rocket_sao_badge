// Rocket SAO firmware: an I2C target for the badge, installed under twiboot.
//
// The badge drives the LP5810 directly. This firmware handles the jobs that
// benefit from steady timing next to the hardware: filtering the light sensor,
// running the transistor-driven LED, and keeping settings in EEPROM.
//
// Registers (the first byte of a write sets the register pointer):
//   0x00 R   ID, always 'R'
//   0x01 R   Firmware version
//   0x02 R   Capability bits, see CAP_*
//   0x03 R   Status bits, see STATUS_*
//   0x10 R   Filtered light, low byte (0-1023, 0 V to VCC)
//   0x11 R   Filtered light, high byte
//   0x12 R/W Lowest light / 4 since reset. Writing restarts min and max
//   0x13 R   Highest light / 4 since reset
//   0x14 R/W Light change that counts as an event
//   0x15 R   Light event counter, wraps at 255
//   0x20 R/W Q1 LED mode, see LED_*
//   0x21 R/W Q1 LED duty, 0-255
//   0x22 R/W Q1 LED blink half period, in 10 ms units
//   0x30 R/W Host present. Non-zero stops standalone startup
//   0x40 R/W EEPROM address, low byte
//   0x41 R/W EEPROM address, high byte
//   0x42 R/W EEPROM data at that address, then the address increments.
//            Access one byte per transfer, and wait for STATUS_EEPROM_BUSY
//            to clear after a write
//   0x7F W   Write CMD_BOOTLOADER to enter twiboot

#include <Wire.h>
#include <avr/eeprom.h>

#define LED_PIN 1
#define SENSOR_PIN A3

#define I2C_ADDR 0x2A
#define LP5810_ADDR 0x50

#define FW_ID 'R'
#define FW_VERSION 1

#define CAP_LIGHT 0x01
#define CAP_LED 0x02
#define CAP_EEPROM 0x04
#define CAP_BOOTLOADER 0x08

#define STATUS_HOST_SEEN 0x01
#define STATUS_STANDALONE 0x02
#define STATUS_EEPROM_BUSY 0x04

#define LED_OFF 0
#define LED_ON 1
#define LED_PWM 2
#define LED_BLINK 3

#define CMD_BOOTLOADER 0xB0
#define BOOTLOADER_START 0x1C00

#define EEPROM_SIZE 512
#define READ_BURST 8  // Fits the 16 byte USI transmit buffer
#define OVERSAMPLES 16
#define FILTER_SHIFT 3
#define DEFAULT_THRESHOLD 16
#define STANDALONE_DELAY_MS 5000

#define LP_DRIVE_CURRENT 0xBF
#define LP_NUM_LEDS 4
#define LP_AEP_SIZE 26
#define LP_AEP_USED 10
#define LP_REG_AEP 0x080

// One LED's breathing animation: pause, playback, PWM1-5, T12, T34, AEU1 count.
const uint8_t BREATHE_AEP[LP_AEP_USED] PROGMEM = {
  0x00, 0x0F, 0, 128, 255, 128, 0, 0x66, 0x66, 0x01
};

volatile uint8_t reg_pointer = 0;
volatile uint8_t status_flags = 0;
volatile uint8_t host_present = 0;
volatile uint8_t light_threshold = DEFAULT_THRESHOLD;
volatile uint8_t light_events = 0;
volatile uint8_t light_low = 255;
volatile uint8_t light_high = 0;
volatile uint16_t light_filtered = 0;
volatile uint8_t led_mode = LED_OFF;
volatile uint8_t led_duty = 0;
volatile uint8_t led_period = 50;
volatile bool led_dirty = true;
volatile uint16_t eeprom_addr = 0;
volatile bool eeprom_pending = false;
volatile uint16_t eeprom_write_addr = 0;
volatile uint8_t eeprom_write_data = 0;
volatile bool bootloader_requested = false;

uint16_t light_state = 0;
uint16_t light_at_event = 0;
bool led_blink_on = false;
unsigned long led_toggled_at = 0;
bool standalone_done = false;

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  pinMode(SENSOR_PIN, INPUT);

  light_state = read_light() << FILTER_SHIFT;
  light_filtered = light_state >> FILTER_SHIFT;
  light_at_event = light_filtered;

  start_target();
}

void loop() {
  if (bootloader_requested) {
    enter_bootloader();
  }
  update_light();
  update_led();
  update_eeprom();
  update_standalone();
}

// Wire.begin(address) clears the callbacks, so they must be attached after it.
void start_target() {
  Wire.begin(I2C_ADDR);
  Wire.onReceive(on_receive);
  Wire.onRequest(on_request);
}

void on_receive(int count) {
  status_flags |= STATUS_HOST_SEEN;
  if (!Wire.available()) {
    return;
  }
  reg_pointer = Wire.read();
  while (Wire.available()) {
    reg_write(reg_pointer, Wire.read());
    reg_pointer++;
  }
}

void on_request() {
  status_flags |= STATUS_HOST_SEEN;
  uint8_t count = reg_pointer == 0x42 ? 1 : READ_BURST;
  for (uint8_t i = 0; i < count; i++) {
    Wire.write(reg_read(reg_pointer + i));
  }
}

uint8_t reg_read(uint8_t reg) {
  switch (reg) {
    case 0x00: return FW_ID;
    case 0x01: return FW_VERSION;
    case 0x02: return CAP_LIGHT | CAP_LED | CAP_EEPROM | CAP_BOOTLOADER;
    case 0x03:
      return status_flags | (eeprom_pending ? STATUS_EEPROM_BUSY : 0);
    case 0x10: return light_filtered & 0xFF;
    case 0x11: return light_filtered >> 8;
    case 0x12: return light_low;
    case 0x13: return light_high;
    case 0x14: return light_threshold;
    case 0x15: return light_events;
    case 0x20: return led_mode;
    case 0x21: return led_duty;
    case 0x22: return led_period;
    case 0x30: return host_present;
    case 0x40: return eeprom_addr & 0xFF;
    case 0x41: return eeprom_addr >> 8;
    case 0x42:
      if (eeprom_pending) {
        return 0xFF;
      } else {
        uint8_t value = eeprom_read_byte((const uint8_t *)eeprom_addr);
        eeprom_addr = (eeprom_addr + 1) % EEPROM_SIZE;
        return value;
      }
    default: return 0;
  }
}

void reg_write(uint8_t reg, uint8_t value) {
  switch (reg) {
    case 0x12:
      light_low = 255;
      light_high = 0;
      break;
    case 0x14: light_threshold = value; break;
    case 0x20:
      led_mode = value;
      led_dirty = true;
      break;
    case 0x21:
      led_duty = value;
      led_dirty = true;
      break;
    case 0x22: led_period = value; break;
    case 0x30: host_present = value; break;
    case 0x40:
      eeprom_addr = (eeprom_addr & 0xFF00) | value;
      break;
    case 0x41:
      eeprom_addr = (eeprom_addr & 0x00FF) | ((uint16_t)(value & 0x01) << 8);
      break;
    case 0x42:
      // A write takes about 3.4 ms, too long for this interrupt.
      if (!eeprom_pending) {
        eeprom_write_addr = eeprom_addr;
        eeprom_write_data = value;
        eeprom_pending = true;
        eeprom_addr = (eeprom_addr + 1) % EEPROM_SIZE;
      }
      break;
    case 0x7F:
      if (value == CMD_BOOTLOADER) {
        bootloader_requested = true;
      }
      break;
  }
}

uint16_t read_light() {
  uint16_t total = 0;
  for (uint8_t i = 0; i < OVERSAMPLES; i++) {
    total += analogRead(SENSOR_PIN);
  }
  return total / OVERSAMPLES;
}

void update_light() {
  light_state += read_light() - (light_state >> FILTER_SHIFT);
  uint16_t level = light_state >> FILTER_SHIFT;

  noInterrupts();
  light_filtered = level;
  interrupts();

  uint8_t coarse = level >> 2;
  if (coarse < light_low) {
    light_low = coarse;
  }
  if (coarse > light_high) {
    light_high = coarse;
  }

  uint16_t change = level > light_at_event ? level - light_at_event
                                           : light_at_event - level;
  if (change >= light_threshold) {
    light_at_event = level;
    light_events++;
  }
}

void update_led() {
  if (led_dirty) {
    led_dirty = false;
    switch (led_mode) {
      case LED_ON: digitalWrite(LED_PIN, HIGH); break;
      case LED_PWM: analogWrite(LED_PIN, led_duty); break;
      case LED_BLINK:
        led_blink_on = false;
        led_toggled_at = millis();
        digitalWrite(LED_PIN, LOW);
        break;
      default: digitalWrite(LED_PIN, LOW); break;
    }
  }
  if (led_mode == LED_BLINK &&
      millis() - led_toggled_at >= (unsigned long)led_period * 10) {
    led_toggled_at = millis();
    led_blink_on = !led_blink_on;
    digitalWrite(LED_PIN, led_blink_on);
  }
}

void update_eeprom() {
  if (eeprom_pending) {
    eeprom_update_byte((uint8_t *)eeprom_write_addr, eeprom_write_data);
    eeprom_pending = false;
  }
}

// On a badge without rocket support nothing talks to us, so briefly become the
// bus controller to start an animation, then go back to being a target.
void update_standalone() {
  if (standalone_done || millis() < STANDALONE_DELAY_MS) {
    return;
  }
  standalone_done = true;
  if (host_present || (status_flags & STATUS_HOST_SEEN)) {
    return;
  }

  Wire.end();
  Wire.begin();
  lp_write(0x000, 0x01);  // Chip enable
  lp_write(0x00D, 0x0B);  // Recommended LSD threshold
  lp_write(0x004, 0x0F);  // Autonomous mode on all LEDs
  lp_write(0x006, 0x0F);  // Exponential dimming on all LEDs
  lp_write(0x010, 0x55);  // Apply configuration
  lp_write(0x020, 0x0F);  // Enable all LEDs
  for (uint8_t led = 0; led < LP_NUM_LEDS; led++) {
    lp_write(0x050 + led, LP_DRIVE_CURRENT);
    uint16_t base = LP_REG_AEP + led * LP_AEP_SIZE;
    for (uint8_t i = 0; i < LP_AEP_SIZE; i++) {
      uint8_t value = i < LP_AEP_USED ? pgm_read_byte(&BREATHE_AEP[i]) : 0;
      lp_write(base + i, value);
    }
  }
  lp_write(0x011, 0xFF);  // Start
  Wire.end();
  status_flags |= STATUS_STANDALONE;
  start_target();
}

void lp_write(uint16_t reg, uint8_t value) {
  // The LP5810 takes register bits 9:8 as the low bits of its I2C address.
  Wire.beginTransmission(uint8_t(LP5810_ADDR | (reg >> 8)));
  Wire.write(uint8_t(reg & 0xFF));
  Wire.write(value);
  Wire.endTransmission();
}

// Jumps straight to twiboot instead of using a watchdog reset. twiboot doesn't
// clear the watchdog on the ATtiny85, so a watchdog reset would keep repeating.
void enter_bootloader() {
  noInterrupts();
  USICR = 0;
  USISR = 0xF0;
  ADCSRA = 0;
  TIMSK = 0;
  TCCR0A = 0;
  TCCR0B = 0;
  TCCR1 = 0;
  GTCCR = 0;
  DDRB = 0;
  PORTB = 0;
  ((void (*)(void))(BOOTLOADER_START / 2))();
}
