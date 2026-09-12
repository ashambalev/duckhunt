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
#include <math.h>
#include <Wiimote.h>

Wiimote   wii;
static uint16_t g_handle = 0;

// One IR blob in the camera's own 1024x768 space. Declared up here because
// the Arduino preprocessor writes its function prototypes above the sketch.
struct Dot { float x, y; int size; };   // size: the blob's extent, 0..15

// Rumble recoil: a short pulse of the remote's vibration motor on a trigger pull.
// Recoil is GONE. The motor lives in the remote and runs off the same two AA
// cells as its radio, and the first measurement pointed straight at it: windows
// with 21-32 shots gave 47-66 reports a second against 88-92 in the windows
// with no shooting. The A/B run then cleared it — the half WITH recoil was the
// better half (80-83/s) — so the motor was not the cause, but nobody wants it
// back either, and one output report per shot is one less thing on the link.
//
// What that A/B did leave behind is a better question: the recoil sent two
// output reports per shot, and the stream was fine while it did. Bluetooth
// Classic links can drop into sniff mode when the host stops talking, which
// costs exactly this kind of latency. So the keep-alive below sends the same
// kind of packet on a timer — set_rumble(false), which runs no motor at all —
// and 'k' turns it on, to see whether it is the traffic that keeps the link
// awake. Off by default, because it is a hypothesis, not a fix.
static const unsigned long KEEPALIVE_MS = 250;
static bool KEEPALIVE_ON = false;
static bool          g_prev_b = false;
static unsigned long g_keepalive_last = 0;

// Step-by-step IR camera enabling: one command per IR_STEP_MS, so the remote has
// time to acknowledge each register write (sent in one burst, they get lost).
// IR sensitivity. The two blocks end in a pair of thresholds, and the lower they
// are the fainter a dot the camera will still latch onto. These are the Wii's own
// "level 5" (its most sensitive) values, chosen after a run where all four beacons
// came back as blobs of size 0-2 out of 15 and kept dropping out. The gentler
// setting the bridge used before is one line down if a bright room starts
// producing phantom dots (reflections, sunlight, an incandescent bulb).
static const uint8_t SENS1[9] = {0x07,0x00,0x00,0x71,0x01,0x00,0x72,0x00,0x20};
static const uint8_t SENS2[2] = {0x1F,0x03};
// gentler: SENS1 {0x00,0x00,0x00,0x00,0x00,0x00,0x90,0x00,0x41}, SENS2 {0x40,0x00}
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
    case 8: wii.request_status(g_handle); break;   // -> "# remote battery: ..."
    default: g_ir_step = 99; return;                                     // 99 = done
  }
  g_ir_step++;
}

// ---- 4 IR dots -> aim point -----------------------------------------------
// With the four corner beacons lit, the four blobs the camera reports ARE the
// screen rectangle as seen down the barrel. The aim point is then simply where
// the CENTRE of the camera image falls inside that rectangle — a projective
// (homography) mapping, which absorbs distance, tilt and roll for free. Below
// four dots it degrades to the old centroid guess rather than freezing.
static const int   CAM_W = 1024, CAM_H = 768;
static const float CAM_CX = 512.0f, CAM_CY = 384.0f;   // the barrel points here

// The camera's axes against the screen's, both settled on the hardware by a test
// with nothing to mislabel: cover the two top beacons and watch which dots go
// dark. The ones low in the sensor frame did, so the sensor's Y runs against the
// screen's while its X runs with it. (Two earlier "it is inverted" reports came
// from a build where the fallback still shared these flags with the homography,
// which needs them the other way round — hence the boot banner that now prints
// the flags, so a log can never again be about a firmware nobody was running.)
// Not const: 'x' and 'y' on the serial port flip them while the gun is in your
// hands. Four separate measurements agreed on these values and the crosshair
// still felt wrong, so the argument is settled the short way — flip it, look at
// the screen, and whatever you leave it on is printed and logged.
static bool CAM_MIRROR_X = false;
static bool CAM_MIRROR_Y = true;

// Where the beacon rectangle sits against the screen it surrounds — its centre
// and its size, in fractions of that screen. LEAVE THESE AT 0.5/0.5/1.0/1.0: the
// same correction now lives in [gun] in settings.toml on the Mac side (frame,
// beacon_w/h, beacon_cx/cy), where the beacons moving to another display costs an
// edit instead of a flash, and where the game can also say the LEDs are on the
// corners of its own letterboxed picture rather than the screen's. They are kept
// here only so a gun can be aimed without the game. docs/BUILD.md walks
// through it.
static const float BEACON_CX = 0.5f, BEACON_CY = 0.5f;
static const float BEACON_W  = 1.0f, BEACON_H  = 1.0f;

// Diagnostics: the last decoded dots, dumped from loop() so you can see whether
// all four beacons are actually in view. Twice a second by default (cheap enough
// to leave on while playing); tools/ir_view.py asks for every frame with 'd'.
static Dot           g_dots[4];
static int           g_dots_n = 0;
static bool          g_dots_fresh = false;
static unsigned long g_dump_ms = 500;      // 0 = every report, <0 impossible: 'o' = off
static bool          g_dump_on = true;
// How many reports the remote actually delivered in the last second, printed
// once a second. This is the number that splits the two explanations of a
// sagging stream: if the bridge says 96/s while the Mac counts 60/s, the loss is
// on the wire or in this sketch; if the bridge itself says 60/s, the Bluetooth
// link is dropping the reports and nothing on the Mac can fix it.
static uint32_t      g_reports = 0;
// The radio's own opinion of itself, asked for once a second. The report rate
// alone cannot tell why it sags; these two can. A weak signal (rssi well below
// -80) is distance, a body in the way, or the antenna. A strong signal with poor
// quality (the controller's bit-error estimate, 255 = clean) is interference —
// something else transmitting on 2.4 GHz.
static int8_t        g_rssi = 0;
static uint8_t       g_quality = 0;
static bool          g_rssi_seen = false;      // do not print the initial zero:
static bool          g_link_fresh = false;     // it reads like a perfect signal

// The 12 IR bytes of report 0x33 -> up to 4 visible dots.
static int ir_dots(const uint8_t* ir, Dot* out) {
  int n = 0;
  for (int i = 0; i < 4; i++) {
    uint8_t b0 = ir[i*3], b1 = ir[i*3+1], b2 = ir[i*3+2];
    if (b0 == 0xFF && b1 == 0xFF) continue;            // dot not visible
    out[n].x = (float)(b0 | ((b2 & 0x30) << 4));
    out[n].y = (float)(b1 | ((b2 & 0xC0) << 2));
    out[n].size = b2 & 0x0F;      // how big the blob is: a dim beacon reads small
    n++;
  }
  return n;
}

// Four dots -> the quad in image order (top-left, top-right, bottom-right,
// bottom-left), by which side of the centroid each one falls. Reliable for a
// rectangle viewed from anywhere in front of it; two dots landing in the same
// quadrant means it is not a clean rectangle (a reflection, or a stray IR
// source), so the caller falls back.
static bool sort_quad(const Dot* d, Dot* q) {
  float cx = 0, cy = 0;
  for (int i = 0; i < 4; i++) { cx += d[i].x; cy += d[i].y; }
  cx /= 4.0f; cy /= 4.0f;
  int idx[4] = { -1, -1, -1, -1 };
  for (int i = 0; i < 4; i++) {
    int slot = (d[i].y > cy) ? ((d[i].x > cx) ? 2 : 3)
                             : ((d[i].x > cx) ? 1 : 0);
    if (idx[slot] >= 0) return false;
    idx[slot] = i;
  }
  for (int i = 0; i < 4; i++) q[i] = d[idx[i]];
  return true;
}

// Where (px,py) sits inside the quad, in 0..1 along its own two axes. Heckbert's
// unit-square -> quad projective map, built from the four corners and then
// inverted (3x3 adjugate; the determinant cancels in the u=U/W division).
static bool aim_in_quad(const Dot* q, float px, float py, float& u, float& v) {
  float x0=q[0].x, y0=q[0].y, x1=q[1].x, y1=q[1].y;
  float x2=q[2].x, y2=q[2].y, x3=q[3].x, y3=q[3].y;
  float sx = x0 - x1 + x2 - x3;
  float sy = y0 - y1 + y2 - y3;
  float a, b, c, d, e, f, g, h;
  if (fabsf(sx) < 1e-4f && fabsf(sy) < 1e-4f) {        // no perspective -> affine
    a = x1-x0; b = x2-x1; c = x0;
    d = y1-y0; e = y2-y1; f = y0;
    g = 0.0f;  h = 0.0f;
  } else {
    float dx1 = x1-x2, dx2 = x3-x2, dy1 = y1-y2, dy2 = y3-y2;
    float den = dx1*dy2 - dx2*dy1;
    if (fabsf(den) < 1e-6f) return false;              // degenerate quad
    g = (sx*dy2 - dx2*sy) / den;
    h = (dx1*sy - sx*dy1) / den;
    a = x1-x0+g*x1; b = x3-x0+h*x3; c = x0;
    d = y1-y0+g*y1; e = y3-y0+h*y3; f = y0;
  }
  float A = e - f*h,       B = c*h - b,   C = b*f - c*e;
  float D = f*g - d,       E = a - c*g,   F = c*d - a*f;
  float G = d*h - e*g,     H = b*g - a*h, I = a*e - b*d;
  float U = A*px + B*py + C;
  float V = D*px + E*py + F;
  float W = G*px + H*py + I;
  if (fabsf(W) < 1e-9f) return false;
  u = U / W; v = V / W;
  return true;
}

static bool computeAim(const uint8_t* ir, int& outX, int& outY) {
  Dot d[4], q[4];
  int n = ir_dots(ir, d);
  g_dots_n = n;
  for (int i = 0; i < n; i++) g_dots[i] = d[i];
  g_dots_fresh = true;
  if (n == 0) return false;

  float u, v;
  if (n == 4 && sort_quad(d, q) && aim_in_quad(q, CAM_CX, CAM_CY, u, v)) {
    // The homography reads the aim off the rectangle itself, so here the flags
    // mean only "which way do the sensor's axes run against the screen's".
    if (CAM_MIRROR_X) u = 1.0f - u;
    if (CAM_MIRROR_Y) v = 1.0f - v;
    // u,v are fractions of the BEACON rectangle; restate them as fractions of
    // the display, which is what the game expects to receive. (After the flips,
    // because BEACON_CX/CY are given in the screen's orientation, not the
    // sensor's.)
    u = BEACON_CX + (u - 0.5f) * BEACON_W;
    v = BEACON_CY + (v - 0.5f) * BEACON_H;
  } else {
    // FALLBACK: fewer than four beacons in view (or they do not form a quad).
    // Here the aim is the dot centroid, which slides the OPPOSITE way to the
    // barrel — swing right and the whole picture shifts left in the frame. So
    // this branch wants the axes the other way round from the homography, and
    // sharing one pair of flags between the two is what made the crosshair
    // invert whenever a beacon dropped out. The scale is still arbitrary and
    // drifts with distance; only the direction is worth anything.
    float sx = 0, sy = 0;
    for (int i = 0; i < n; i++) { sx += d[i].x; sy += d[i].y; }
    u = (sx / n) / (float)(CAM_W - 1);
    v = (sy / n) / (float)(CAM_H - 1);
    if (!CAM_MIRROR_X) u = 1.0f - u;
    if (!CAM_MIRROR_Y) v = 1.0f - v;
  }

  outX = constrain((int)(u * 1000.0f), 0, 1000);
  outY = constrain((int)(v * 1000.0f), 0, 1000);
  return true;
}

// Status lines get a '#' prefix so they stand out from the data (the game ignores
// non-numeric lines anyway).
static void status(const char* s) { Serial.print("# "); Serial.println(s); }

// Printed at boot and again on every flip, so a log always names the axes it was
// recorded under.
static void print_axes() {
  Serial.printf("# axes: MIRROR_X=%d MIRROR_Y=%d\n",
                (int)CAM_MIRROR_X, (int)CAM_MIRROR_Y);
}

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
      wii.scan(true);
      break;
    case WIIMOTE_EVENT_RSSI:
      // A fresh connection answers 0 before it has measured anything, and 0 dBm
      // is not a signal any radio in a room produces — so it means "not yet".
      if (len >= 1 && data[0] != 0) { g_rssi = (int8_t)data[0]; g_rssi_seen = true; }
      break;
    case WIIMOTE_EVENT_LINK_QUALITY:
      if (len >= 1) { g_quality = data[0]; g_link_fresh = true; }
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
        g_prev_b = b_now;
        // More of the remote's buttons, so the game has something to bind to
        // without a keyboard: A hides the crosshair, HOME is spare. Byte layout
        // of report 0x33: data[2] = dpad/plus, data[3] = two/one/B/A/minus/home.
        if (data[3] & 0x08) buttons |= 0x02;                // A
        if (data[3] & 0x80) buttons |= 0x04;                // HOME
        int ax = -1, ay = -1;
        g_reports++;
        computeAim(&data[7], ax, ay);
        Serial.printf("%d,%d,%u\n", ax, ay, buttons);       // -> to the game
      } else if (len >= 8 && data[1] == 0x20) {
        // Status report: (a1) 20 BB BB LF 00 00 VV — VV is the battery level, and
        // the remote sends this by itself on every connect, so the number is free
        // and arrives exactly when it is wanted. Worth having in the log: tired
        // AA cells are what makes the link drop under continuous IR reporting,
        // and "the gun lags later in the game" looks identical to that. 0xC0 is
        // about full; the percentage is rough on purpose.
        Serial.printf("# remote battery: 0x%02X (~%d%% of full)\n",
                      data[7], (int)((data[7] * 100) / 0xC0));
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
  // The aim line is printed from inside the Bluetooth callback (see
  // wiimote_cb), so a full UART buffer does not just delay a print — it stalls
  // the BT stack, and the next reports queue up behind it. That is measurable:
  // a run with the dot dump on every report showed the gap between reports
  // doubling (18 -> 33 ms) and the rate dropping (88 -> 67/s) exactly in the
  // windows where four beacons were in view, i.e. when the dump lines got long.
  // A TX buffer big enough for a whole clump of reports keeps the callback from
  // ever waiting on the wire.
  Serial.setTxBufferSize(2048);
  Serial.begin(115200);
  delay(200);
  status("Duck Hunt Wiimote bridge (USB). Initializing BT...");
  // Which build is actually running, printed where every log picks it up: after
  // a couple of flag flips guessed from how the crosshair felt, "was that the
  // firmware I think it was?" stopped being a rhetorical question.
  Serial.printf("# build %s %s | MIRROR_X=%d MIRROR_Y=%d | beacon %.2fx%.2f @ %.2f,%.2f"
                " | no recoil | keep-alive %s ('k')\n",
                __DATE__, __TIME__, (int)CAM_MIRROR_X, (int)CAM_MIRROR_Y,
                BEACON_W, BEACON_H, BEACON_CX, BEACON_CY,
                KEEPALIVE_ON ? "ON" : "off");
  wii.init(wiimote_cb);
}

void loop() {
  wii.handle();                                          // services the BT stack
  ir_sequencer();                                        // step-by-step IR enabling

  // One-letter commands on the same port, for the debugging tools:
  //   d = dump the dots on every camera report (tools/ir_view.py wants this)
  //   s = back to twice a second (the default)      o = no dumping at all
  //   k = keep-alive on/off (an output report every 250 ms, no motor)
  while (Serial.available()) {
    switch (Serial.read()) {
      case 'd': g_dump_ms = 0;   g_dump_on = true;  status("dot dump: every report"); break;
      case 's': g_dump_ms = 500; g_dump_on = true;  status("dot dump: 2 Hz"); break;
      case 'o': g_dump_on = false;                  status("dot dump: off"); break;
      case 'k':
        KEEPALIVE_ON = !KEEPALIVE_ON;
        Serial.printf("# keep-alive: %s (an output report every %lu ms, no motor)\n",
                      KEEPALIVE_ON ? "ON" : "off", KEEPALIVE_MS);
        break;
      case 'x': CAM_MIRROR_X = !CAM_MIRROR_X; print_axes(); break;
      case 'y': CAM_MIRROR_Y = !CAM_MIRROR_Y; print_axes(); break;
      case '?': print_axes(); break;
      default: break;                               // newlines and other noise
    }
  }

  // DIAGNOSTICS: how many beacons the camera has in view and where they are.
  // This is the line to watch when the aim goes wrong — four dots in a sane
  // rectangle means the homography has everything it needs.
  static unsigned long last_dump = 0;
  // ... and the dump waits its turn: if the buffer is already filling, the aim
  // lines have the right of way and this frame's dots are simply skipped. A
  // diagnostic that adds latency to the thing it is diagnosing is worse than no
  // diagnostic.
  if (g_dump_on && g_dots_fresh && millis() - last_dump >= g_dump_ms
      && Serial.availableForWrite() > 96) {
    last_dump = millis();
    g_dots_fresh = false;
    char buf[120];
    int k = snprintf(buf, sizeof(buf), "# dots n=%d", g_dots_n);
    for (int i = 0; i < g_dots_n && k > 0 && k < (int)sizeof(buf); i++)
      k += snprintf(buf + k, sizeof(buf) - k, " (%d,%d,%d)",
                    (int)g_dots[i].x, (int)g_dots[i].y, g_dots[i].size);
    Serial.println(buf);
  }

  // the remote's own delivery rate, once a second (cheap, and it is the number
  // that tells the Bluetooth link apart from everything downstream of it)
  static unsigned long last_rate = 0;
  if (millis() - last_rate >= 1000) {
    last_rate = millis();
    if (g_handle && Serial.availableForWrite() > 48)
      Serial.printf("# rate: %u/s from the remote\n", g_reports);
    g_reports = 0;
    // and ask the controller how the link itself is doing; the answers arrive as
    // events and get printed below, so this costs nothing in the callback
    if (g_handle) { wii.read_rssi(g_handle); wii.read_link_quality(g_handle); }
  }

  if (g_link_fresh && g_rssi_seen && Serial.availableForWrite() > 64) {
    g_link_fresh = false;
    // This controller answers in absolute dBm, which the numbers settled: -40
    // across the desk, -51 at playing distance, tracking the report rate all the
    // way. (The 0 that showed up in the first run was this variable before any
    // answer had arrived, which is why the print now waits for one.)
    // Quality is the controller's own bit-error estimate, 255 = clean.
    Serial.printf("# link: rssi %d dBm, quality %u/255\n",
                  (int)g_rssi, g_quality);
  }

  // the keep-alive: one harmless output report on a timer, to test whether a
  // link that is being talked to stays faster than one that is not
  if (KEEPALIVE_ON && g_handle && millis() - g_keepalive_last >= KEEPALIVE_MS) {
    g_keepalive_last = millis();
    wii.set_rumble(g_handle, false);        // rumble bit clear = motor stays off
  }
}
