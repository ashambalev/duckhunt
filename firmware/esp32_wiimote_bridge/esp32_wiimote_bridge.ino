/*
 * Duck Hunt — Wiimote -> Mac bridge (PATH B, over USB-Serial)
 * -----------------------------------------------------------
 * Board    : an original ESP32 (WROOM-32/-32U) — ONLY it speaks the Bluetooth
 *            Classic the Wii Remote needs. An ESP32-S3/C3 will NOT do.
 * Library  : firmware/libs/Wiimote (takeru/Wiimote plus the Duck Hunt patch:
 *            enable_ir). Compile with  --libraries firmware/libs.
 * Chain    : Wiimote -> (Bluetooth) -> ESP32 -> (USB-Serial) -> Mac.
 *            The remote is wireless; the ESP32 sits on the Mac's USB. No WiFi.
 *
 * Output (USB-Serial, 115200) — the same protocol as every other version:
 *     x,y,b\n   (x,y = aim point 0..1000, -1,-1 if no dots; b: bit0 = trigger)
 * On the Mac:  python3 main.py --serial /dev/tty.usbserial-XXXX
 * The game's parser (serial_gun.py) ignores anything that is not an "x,y,b" line,
 * so the occasional status messages below (sent on the same Serial) do not
 * bother it.
 *
 * Pairing: plug the ESP32 in over USB, then press the red SYNC button on the
 * remote (under the cover) for the FIRST pairing; after that the A or 1+2 buttons
 * are enough.
 */

#include <Arduino.h>
#include <Wiimote.h>

Wiimote   wii;
static uint16_t g_handle = 0;

// Rumble recoil: a short pulse of the remote's vibration motor on a trigger pull.
static const unsigned long RUMBLE_MS = 90;
static bool          g_prev_b = false;
static unsigned long g_rumble_until = 0;

// Step-by-step IR camera enabling: one command per IR_STEP_MS, so the remote has
// time to acknowledge each register write (sent in one burst, they get lost).
static const uint8_t SENS1[9] = {0x00,0x00,0x00,0x00,0x00,0x00,0x90,0x00,0x41};
static const uint8_t SENS2[2] = {0x40,0x00};
static const uint8_t V08[1]   = {0x08};
static const uint8_t MODE3[1] = {0x03};
static const unsigned long IR_STEP_MS = 60;
static int           g_ir_step = -1;      // -1 = not started / done
static unsigned long g_ir_last = 0;

static void ir_sequencer() {
  if (g_ir_step < 0 || g_handle == 0) return;
  if (millis() - g_ir_last < IR_STEP_MS) return;
  g_ir_last = millis();
  switch (g_ir_step) {
    case 0: wii.ir_send_report(g_handle, 0x13, 0x04); break;             // enable IR
    case 1: wii.ir_send_report(g_handle, 0x1A, 0x04); break;             // enable IR 2
    case 2: wii.ir_write_register(g_handle, 0xB00030, V08, 1); break;
    case 3: wii.ir_write_register(g_handle, 0xB00000, SENS1, 9); break;
    case 4: wii.ir_write_register(g_handle, 0xB0001A, SENS2, 2); break;
    case 5: wii.ir_write_register(g_handle, 0xB00033, MODE3, 1); break;  // mode 3 (extended)
    case 6: wii.ir_write_register(g_handle, 0xB00030, V08, 1); break;
    case 7: wii.set_report_mode(g_handle, 0x33, true); status("IR camera enabled (0x33 continuous)."); break;
    default: g_ir_step = 99; return;                                     // 99 = done
  }
  g_ir_step++;
}

// The 4 IR dots from report 0x33 -> an aim point in 0..1000. A STUB (averaging the
// visible dots), as in the other firmwares. A proper four-corner homography is a TODO.
static bool computeAim(const uint8_t* ir, int& outX, int& outY) {
  long sx = 0, sy = 0; int n = 0;
  for (int i = 0; i < 4; i++) {
    uint8_t b0 = ir[i*3], b1 = ir[i*3+1], b2 = ir[i*3+2];
    if (b0 == 0xFF && b1 == 0xFF) continue;          // dot not visible
    int x = b0 | ((b2 & 0x30) << 4);
    int y = b1 | ((b2 & 0xC0) << 2);
    sx += x; sy += y; n++;
  }
  if (n == 0) return false;
  float cx = (float)sx / n, cy = (float)sy / n;
  // Axis signs are deliberately left alone: with 4 beacons this whole function is
  // replaced by a homography built from the corner correspondences, and that
  // transform carries the mirroring itself. (X is mirrored here, Y is not — an
  // asymmetry that only matters for one-dot testing, so it is not worth chasing.)
  outX = (int)((1.0f - cx / 1023.0f) * 1000.0f);
  outY = (int)((cy / 767.0f) * 1000.0f);
  outX = constrain(outX, 0, 1000);
  outY = constrain(outY, 0, 1000);
  return true;
}

// Status lines get a '#' prefix so they stand out from the data (the game ignores
// non-numeric lines anyway).
static void status(const char* s) { Serial.print("# "); Serial.println(s); }

static void wiimote_cb(wiimote_event_type_t ev, uint16_t handle, uint8_t* data, size_t len) {
  switch (ev) {
    case WIIMOTE_EVENT_INITIALIZE:
      status("BT init. Press SYNC (first time) or A/1+2 on the remote...");
      wii.scan(true);
      break;
    case WIIMOTE_EVENT_NEW:
      status("New remote, authenticating...");
      wii.initiate_auth(handle);
      break;
    case WIIMOTE_EVENT_CONNECT:
      g_handle = handle;
      g_ir_step = -1;
      status("Remote connected.");
      wii.set_led(handle, 0x01);
      wii.scan(false);
      break;
    case WIIMOTE_EVENT_DISCONNECT:
      status("Remote disconnected. Waiting for pairing again...");
      g_handle = 0;
      g_ir_step = -1;
      g_prev_b = false;
      g_rumble_until = 0;
      wii.scan(true);
      break;
    case WIIMOTE_EVENT_DATA:
      // The first report to arrive means the channel is up -> start the IR sequence.
      if (g_ir_step < 0 && g_handle != 0) {
        status("Channel ready, enabling the IR camera step by step...");
        g_ir_step = 0; g_ir_last = 0;
      }
      // Report 0x33: [0]=A1 [1]=33 [2..3]=buttons [4..6]=accel [7..18]=12 IR bytes
      if (len >= 19 && data[1] == 0x33) {
        bool b_now = (data[3] & 0x04);
        uint8_t buttons = b_now ? 0x01 : 0x00;              // the B button is the trigger
        if (b_now && !g_prev_b && g_handle) {               // rising edge -> recoil
          wii.set_rumble(g_handle, true);
          g_rumble_until = millis() + RUMBLE_MS;
        }
        g_prev_b = b_now;
        int ax = -1, ay = -1;
        computeAim(&data[7], ax, ay);
        Serial.printf("%d,%d,%u\n", ax, ay, buttons);       // -> to the game
      } else if (len >= 2) {
        // DIAGNOSTICS: which report type the remote actually sends (every ~40th)
        static uint32_t c = 0;
        if ((c++ % 40) == 0) Serial.printf("# rpt id=0x%02X len=%d\n", data[1], (int)len);
      }
      break;
    default:
      break;
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  status("Duck Hunt Wiimote bridge (USB). Initializing BT...");
  wii.init(wiimote_cb);
}

void loop() {
  wii.handle();                                          // services the BT stack
  ir_sequencer();                                        // step-by-step IR enabling

  // switch the rumble motor off after the short pulse (non-blocking)
  if (g_rumble_until && millis() > g_rumble_until) {
    if (g_handle) wii.set_rumble(g_handle, false);
    g_rumble_until = 0;
  }
}
