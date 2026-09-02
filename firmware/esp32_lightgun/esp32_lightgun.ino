/*
 * Duck Hunt — light gun firmware (SKELETON)
 * -----------------------------------------
 * Platform : ESP32-S3 (native USB CDC — shows up on a Mac as /dev/tty.usbmodem*)
 * Sensor   : PixArt IR camera (DFRobot Positioning IR Camera SEN0158 /
 *            PAJ7025 chip — the same one as in the Wiimote). Reports up to 4
 *            bright IR dots over I2C (X: 0..1023, Y: 0..767).
 * Beacons  : 4 940 nm IR LEDs at the corners of the Mac's screen.
 * Trigger  : a microswitch on a GPIO (INPUT_PULLUP).
 *
 * Serial output, one line per frame:   x,y,b\n
 *   x,y — the aim point, 0..1000 (normalized); -1,-1 if the beacons are not visible
 *   b   — button mask: bit0 = trigger
 *
 * Matches the parser in duckhunt/input/serial_gun.py.
 *
 * The TODOs mark what gets finished in Stage 3.
 */

#include <Wire.h>

// ---- pins -------------------------------------------------------------
static const int PIN_SDA     = 8;   // TODO: match your own ESP32-S3 wiring
static const int PIN_SCL     = 9;
static const int PIN_TRIGGER = 4;   // trigger, to GND through a microswitch
// static const int PIN_SOLENOID = 5; // Stage 4: recoil via a MOSFET

// ---- PixArt IR camera (I2C addr 0x58) --------------------------------
static const uint8_t IRCAM_ADDR = 0x58;

// The classic Wii/PixArt IR camera init sequence.
static void ircamWrite(uint8_t a, uint8_t b) {
  Wire.beginTransmission(IRCAM_ADDR);
  Wire.write(a);
  Wire.write(b);
  Wire.endTransmission();
  delay(10);
}

static void ircamInit() {
  ircamWrite(0x30, 0x01);
  ircamWrite(0x30, 0x08);
  ircamWrite(0x06, 0x90);
  ircamWrite(0x08, 0xC0);
  ircamWrite(0x1A, 0x40);
  ircamWrite(0x33, 0x33);
  delay(100);
}

// Reads 4 dots. Returns how many are visible (coordinates in px[], py[]).
static int ircamRead(int px[4], int py[4]) {
  Wire.beginTransmission(IRCAM_ADDR);
  Wire.write(0x36);
  Wire.endTransmission();
  Wire.requestFrom(IRCAM_ADDR, (uint8_t)16);

  uint8_t buf[16];
  int n = 0;
  while (Wire.available() && n < 16) buf[n++] = Wire.read();
  if (n < 16) return 0;

  int visible = 0;
  for (int i = 0; i < 4; i++) {
    uint8_t *s = &buf[1 + i * 3];
    int x = s[0] + ((s[2] & 0x30) << 4);
    int y = s[1] + ((s[2] & 0xC0) << 2);
    if (x == 1023 && y == 1023) { px[i] = -1; py[i] = -1; }      // dot not visible
    else { px[i] = x; py[i] = y; visible++; }
  }
  return visible;
}

// ---- mapping camera dots onto screen coordinates ----------------------
// TODO (Stage 3): a proper four-corner homography ("aim at the corners"
// calibration). For now a stub: average the visible dots and map the camera's raw
// range (0..1023 / 0..767) linearly onto 0..1000. Crude, but it aims.
static bool computeAim(const int px[4], const int py[4], int &outX, int &outY) {
  long sx = 0, sy = 0; int cnt = 0;
  for (int i = 0; i < 4; i++) {
    if (px[i] >= 0) { sx += px[i]; sy += py[i]; cnt++; }
  }
  if (cnt == 0) return false;
  float cx = (float)sx / cnt;
  float cy = (float)sy / cnt;
  // the camera sees the screen mirrored — invert X
  outX = (int)((1.0f - cx / 1023.0f) * 1000.0f);
  outY = (int)((cy / 767.0f) * 1000.0f);
  outX = constrain(outX, 0, 1000);
  outY = constrain(outY, 0, 1000);
  return true;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TRIGGER, INPUT_PULLUP);
  // pinMode(PIN_SOLENOID, OUTPUT);
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);
  ircamInit();
}

void loop() {
  int px[4], py[4];
  int visible = ircamRead(px, py);

  int ax = -1, ay = -1;
  if (visible > 0) computeAim(px, py, ax, ay);

  uint8_t buttons = 0;
  if (digitalRead(PIN_TRIGGER) == LOW) {   // pressed (PULLUP)
    buttons |= 0x01;
    // digitalWrite(PIN_SOLENOID, HIGH); delay... — Stage 4, and non-blocking!
  }

  Serial.print(ax); Serial.print(',');
  Serial.print(ay); Serial.print(',');
  Serial.println(buttons);

  delay(8);  // ~120 Hz polling; tighten this when moving to BLE
}
