#ifndef _WIIMOTE_H_
#define _WIIMOTE_H_

#include <cstdint>

enum wiimote_event_type_t {
  WIIMOTE_EVENT_INITIALIZE,
  WIIMOTE_EVENT_SCAN_START,
  WIIMOTE_EVENT_SCAN_STOP,
  WIIMOTE_EVENT_NEW,
  WIIMOTE_EVENT_CONNECT,
  WIIMOTE_EVENT_DISCONNECT,
  WIIMOTE_EVENT_DATA,
  // --- Duck Hunt patch: radio link diagnostics. data[0] carries the value:
  // RSSI as a SIGNED byte, link quality as 0..255 (bigger is better).
  WIIMOTE_EVENT_RSSI,
  WIIMOTE_EVENT_LINK_QUALITY,
  // --- Duck Hunt patch: how the pairing attempt ended. data[0] is the HCI
  // status, 0x00 = paired. Anything else means the PIN was not the one this
  // remote was waiting for (see wiimote_pin_t), and the remote drops the link.
  WIIMOTE_EVENT_AUTH_COMPLETE,
  // --- Duck Hunt patch: the controller's answer to set_afh_channel_map().
  // data[0] is the HCI status, 0x00 = the map was taken. 0x12 (invalid
  // parameters) is what fewer than 20 usable channels comes back as.
  WIIMOTE_EVENT_AFH_STATUS
};

// --- Duck Hunt patch: which PIN answers the controller's PIN request ---------
// The Wii Remote asks for a different PIN depending on which button put it in
// discoverable mode, and gets no say in it afterwards:
//   red SYNC button  -> the PIN is the HOST's bluetooth address (LSB first),
//                       and the remote stores the host, so pressing A later
//                       reconnects it on its own.
//   1 + 2 together   -> the PIN is the REMOTE's OWN address (LSB first), and
//                       nothing is stored: it is a one-off connection.
// Answering with the wrong one fails authentication and the remote hangs up,
// which is exactly what "SYNC works but 1+2 does not" looks like.
enum wiimote_pin_t {
  WIIMOTE_PIN_HOST,
  WIIMOTE_PIN_REMOTE
};

enum balance_position_type_t {
  BALANCE_POSITION_TOP_RIGHT,
  BALANCE_POSITION_BOTTOM_RIGHT,
  BALANCE_POSITION_TOP_LEFT,
  BALANCE_POSITION_BOTTOM_LEFT,
};

typedef void (* wiimote_callback_t)(wiimote_event_type_t event_type, uint16_t handle, uint8_t *data, size_t len);


class Wiimote {
  public:
    void init(wiimote_callback_t cb);
    void handle();
    void scan(bool enable);
    void _callback(wiimote_event_type_t event_type, uint16_t handle, uint8_t *data, size_t len);
    void set_led(uint16_t handle, uint8_t leds);
    void set_rumble(uint16_t handle, bool rumble);
    void get_balance_weight(uint8_t *data, float *weight);
    void initiate_auth(uint16_t handle);
    void disconnect(uint16_t handle);
    // --- Duck Hunt patch: pairing that does not need the hidden SYNC button ---
    void set_pin_source(wiimote_pin_t source);       // which PIN to answer with
    void connect(const uint8_t bd_addr[6]);          // page a known remote directly
    bool get_address(uint16_t handle, uint8_t out[6]);  // who is behind a handle
    // --- Duck Hunt patch: enable the IR camera and send 0x33 reports with 4 dots ---
    void enable_ir(uint16_t handle);                 // all at once (may be too fast)
    // Granular steps for enabling IR STEP BY STEP with pauses (more reliable):
    void ir_send_report(uint16_t handle, uint8_t id, uint8_t val);
    void ir_write_register(uint16_t handle, uint32_t offset, const uint8_t* data, uint8_t len);
    void set_report_mode(uint16_t handle, uint8_t mode, bool cont);
    void request_status(uint16_t handle);            // -> report 0x20, has the battery
    void read_rssi(uint16_t handle);                 // -> WIIMOTE_EVENT_RSSI
    void read_link_quality(uint16_t handle);         // -> WIIMOTE_EVENT_LINK_QUALITY
    // --- Duck Hunt patch: stop hopping onto channels known to be busy --------
    // 10 bytes, one bit per channel, bit 0 = 2402 MHz: set = keep using it,
    // clear = do not. At least 20 must be left set. Controller-wide and not
    // per-link, so it can be sent whether or not a remote is connected, and it
    // only reaches the hop sequence while this side is the piconet's master.
    // -> WIIMOTE_EVENT_AFH_STATUS. Sending nothing leaves the radio exactly as
    // it was: the controller's own adaptive hopping is untouched by this.
    void set_afh_channel_map(const uint8_t map[10]);
  private:
    wiimote_callback_t _wiimote_callback;
};

#endif
