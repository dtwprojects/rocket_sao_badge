// Rocket SAO firmware for use on a shared I2C bus.
//
// Lights the LEDs once at power up, then leaves the bus alone so that the badge
// can be the I2C controller.
//
// The USI must be released after the last transfer. TinyWireM leaves it in
// two-wire mode, where the start detector holds SCL low after any START on the
// bus until firmware clears USISIF. Without release_i2c(), the first START from
// the badge freezes the whole SAO bus until the ATtiny is power cycled.

#include <TinyWireM.h>

#define LED_PIN 1
#define SENSOR_PIN A3
#define BUTTON 4

#define LP5810_ADDR 0x50
#define DRIVE_CURRENT 0xBF

void setup() {
  pinMode(BUTTON, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  pinMode(SENSOR_PIN, INPUT);
  digitalWrite(LED_PIN, LOW);

  delay(1);  // LP5810 needs about 1 ms after power up
  TinyWireM.begin();
  leddriver_w(0x000, 0x01);  // Chip enable
  leddriver_w(0x00D, 0x0B);  // Recommended LSD threshold
  leddriver_w(0x010, 0x55);  // Apply configuration
  leddriver_w(0x020, 0x0F);  // Enable all LEDs
  for (uint8_t i = 0; i < 4; i++) {
    leddriver_w(0x030 + i, DRIVE_CURRENT);
    leddriver_w(0x040 + i, 0xFF);
  }
  release_i2c();
}

void loop() {
}

// Hands SDA and SCL back to the bus by disconnecting the USI from its pins.
void release_i2c() {
  USICR = 0;
  USISR = _BV(USISIF) | _BV(USIOIF) | _BV(USIPF);
  DDRB &= ~(_BV(PB0) | _BV(PB2));
  PORTB &= ~(_BV(PB0) | _BV(PB2));
}

void leddriver_w(uint16_t reg, uint8_t val) {
  // The LP5810 takes register bits 9:8 as the low bits of its I2C address.
  TinyWireM.beginTransmission(LP5810_ADDR | (reg >> 8));
  TinyWireM.send(uint8_t(reg & 0xFF));
  TinyWireM.send(val);
  TinyWireM.endTransmission();
}
