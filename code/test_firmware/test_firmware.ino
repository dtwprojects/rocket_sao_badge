
//#include <avr/io.h>
//#include <avr/interrupt.h>
//#include <TinyWireM.h>
#include <TinyWireM.h>

#define LED_PIN 1
#define SENSOR_PIN A3
#define BUTTON 4
#define LP5810_ADDR 0x50
#define LED0 0x40
#define LED1 0x41
#define LED2 0x42
#define LED3 0x43

int val = 0xff;
unsigned long tm = 0;
unsigned long dt = 0;
uint16_t read_out_delay = 1500;

void read_out(unsigned long inpt,unsigned int dly=read_out_delay);
void read_out(int inpt,unsigned int dly=read_out_delay);
void read_out(uint16_t inpt,unsigned int dly=read_out_delay);
void read_out(uint8_t inpt,unsigned int dly=read_out_delay);

void setup(){
  TinyWireM.begin();
  pinMode(BUTTON,INPUT_PULLUP);
  pinMode(LED_PIN,OUTPUT);
  pinMode(SENSOR_PIN,INPUT);
  digitalWrite(LED_PIN,LOW);
  
  leddriver_w(0x000,0x01);
  leddriver_w(0x00d,0x0b);
  leddriver_w(0x010,0x55);
  leddriver_w(0x020,0x0f);
  leddriver_w(0x030,0xbf);
  leddriver_w(0x031,0xbf);
  leddriver_w(0x032,0xbf);
  leddriver_w(0x033,0xbf);
  leddriver_w(0x040,0xff);
  leddriver_w(0x041,0xff);
  leddriver_w(0x042,0xff);
  leddriver_w(0x043,0xff);
  
}

void loop(){
  tm = micros();
  val = analogRead(SENSOR_PIN);
  while (!digitalRead(BUTTON)){
    read_out(dt);
  }
  dt = micros() - tm;
}

void read_out(unsigned long inpt,unsigned int dly){
  for (int i = 0;i < 29; i = i+4){
    digitalWrite(LED_PIN,HIGH);
    nib_out((inpt >> (28 - i)) & 0xff);
    delay(dly);
    digitalWrite(LED_PIN,LOW);
    delay(dly);
  }
}

void read_out(int inpt,unsigned int dly){
  for (int i = 0;i < 13; i = i+4){
    digitalWrite(LED_PIN,HIGH);
    nib_out((inpt >> (12 - i)) & 0xff);
    delay(dly);
    digitalWrite(LED_PIN,LOW);
    delay(dly);
  }
}

void read_out(uint16_t inpt,unsigned int dly){
  for (int i = 0;i < 13; i = i+4){
    digitalWrite(LED_PIN,HIGH);
    nib_out((inpt >> (12 - i)) & 0xff);
    delay(dly);
    digitalWrite(LED_PIN,LOW);
    delay(dly);
  }
}

void read_out(uint8_t inpt,unsigned int dly){
  for (int i = 0;i < 5; i = i+4){
    digitalWrite(LED_PIN,HIGH);
    nib_out((inpt >> (4 - i)) & 0xff);
    delay(dly);
    digitalWrite(LED_PIN,LOW);
    delay(dly);
  }
}

void all_off(){
  all_leds(0);
}

void all_on(){
  all_leds(255);
}

void all_leds(int inval){
  for (int i=0;i<4;i++){
    dim_led(i,inval);
  }
}

void led_off(char inpt_led){
  leddriver_w(0x40+constrain(inpt_led,0,3),0);
}

void led_on(char inpt_led){
  leddriver_w(0x40+constrain(inpt_led,0,3),255);
}

void nib_out(char inptnib){
  for (char i = 0;i<4;i++){
    leddriver_w(0x40+i,255*((inptnib>>(3-i))&0b1));
  }
}

void data_pulse(uint8_t inpt){
  digitalWrite(LED_PIN,0);
  delay(500);
  for (int i=0;i<8;i++){
    digitalWrite(LED_PIN,HIGH);
    delay(50);
    digitalWrite(LED_PIN,LOW);
    delay(50);
    if ((inpt>>i)&0b1){
      digitalWrite(LED_PIN,HIGH);
    }
    delay(500);
    digitalWrite(LED_PIN,LOW);
    delay(125);
  }
}

void pulse(int inpt){
  digitalWrite(LED_PIN,0);
  delay(500);
  for (int i=0;i<inpt;i++){
    digitalWrite(LED_PIN,HIGH);
    delay(500);
    digitalWrite(LED_PIN,LOW);
    delay(500);
  }
}

void dim_led(char inpt_led,char inval){
  leddriver_w(0x40+constrain(inpt_led,0,3),inval);
}

void leddriver_w(uint32_t in_addr,uint8_t val){
  TinyWireM.beginTransmission(LP5810_ADDR|((in_addr>>7)&0b110));
  TinyWireM.send(uint8_t(in_addr&0xFF));
  TinyWireM.send(val);
  TinyWireM.endTransmission();
}

uint8_t leddriver_r(uint32_t in_addr){
  TinyWireM.beginTransmission(LP5810_ADDR|((in_addr>>7)&0b110)|0b1);
  TinyWireM.send(uint8_t(in_addr&0xFF));
  TinyWireM.endTransmission();
  return(TinyWireM.read());
}
