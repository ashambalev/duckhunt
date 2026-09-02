/*
 * Duck Hunt — light gun firmware, PLAN B (SKELETON)
 * -------------------------------------------------
 * An alternative to the PixArt IR camera, in case it is hard to get hold of.
 *
 * Platform : ESP32-S3-CAM (OV2640 sensor, preferably with PSRAM)
 * Idea     : an ordinary camera grabs a frame and finds the MONITOR RECTANGLE
 *            (the screen boundary / bezel) by edge detection. The aim point is
 *            computed from the position and perspective of that rectangle in the
 *            frame. NO IR LEDs around the screen are needed. Same approach as
 *            ddean-blip/esp32-lightgun.
 * Trigger  : a microswitch on a GPIO (INPUT_PULLUP).
 *
 * Serial output — THE SAME protocol as the IR version:   x,y,b\n
 *   x,y — the aim point, 0..1000 (normalized); -1,-1 if the bezel was not found
 *   b   — button mask: bit0 = trigger
 * Matches the parser in duckhunt/input/serial_gun.py — the game is unchanged.
 *
 * The TODOs mark what is still to be built (the CV is the hard part of Plan B).
 */

#include "esp_camera.h"

// ---- pins ------------------------------------------------------------
static const int PIN_TRIGGER = 4;   // trigger to GND, INPUT_PULLUP
// static const int PIN_SOLENOID = 5; // recoil — as in the IR version

// ---- camera pinout ---------------------------------------------------
// TODO: fill in the pins for your own ESP32-S3-CAM board (Freenove / XIAO Sense /
// AI-Thinker and so on). Below are placeholders; take the real ones from your
// board's camera_pins.h example.
static camera_config_t make_camera_config() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer   = LEDC_TIMER_0;
  // c.pin_d0..d7, pin_xclk, pin_pclk, pin_vsync, pin_href, pin_sscb_sda,
  // c.pin_sscb_scl, pin_pwdn, pin_reset  <- TODO: fill in for your own board
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_GRAYSCALE;   // greyscale — easier edge detection
  c.frame_size   = FRAMESIZE_QVGA;        // 320x240 — a speed/accuracy compromise
  c.fb_count     = 2;
  c.grab_mode    = CAMERA_GRAB_LATEST;
  return c;
}

// ---- finding the monitor bezel and computing the aim point -----------
// TODO (the core Plan B algorithm):
//   1) take the greyscale frame (fb->buf, fb->len, 320x240);
//   2) edge detection (Sobel/threshold) -> the boundary of the bright screen
//      rectangle;
//   3) find the 4 corners of that rectangle;
//   4) homography: the centre of the frame (where the barrel points) -> screen
//      coordinates 0..1000. This is exactly the same maths as the IR version's
//      calibration, only the reference points are the bezel corners rather than
//      4 IR LEDs.
// For now a stub: the bezel is "not found".
static bool computeAim(camera_fb_t *fb, int &outX, int &outY) {
  (void)fb;
  outX = -1;
  outY = -1;
  return false;   // TODO: return true and fill in outX/outY once the CV is done
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TRIGGER, INPUT_PULLUP);

  camera_config_t config = make_camera_config();
  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("camera init FAILED — check the pinout/PSRAM");
  }
}

void loop() {
  camera_fb_t *fb = esp_camera_fb_get();

  int ax = -1, ay = -1;
  if (fb) {
    computeAim(fb, ax, ay);
    esp_camera_fb_return(fb);   // IMPORTANT: return the buffer or it will hang
  }

  uint8_t buttons = 0;
  if (digitalRead(PIN_TRIGGER) == LOW) buttons |= 0x01;

  Serial.print(ax); Serial.print(',');
  Serial.print(ay); Serial.print(',');
  Serial.println(buttons);
}
