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
  WIIMOTE_EVENT_DATA
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
    // --- Duck Hunt patch: enable the IR camera and send 0x33 reports with 4 dots ---
    void enable_ir(uint16_t handle);                 // all at once (may be too fast)
    // Granular steps for enabling IR STEP BY STEP with pauses (more reliable):
    void ir_send_report(uint16_t handle, uint8_t id, uint8_t val);
    void ir_write_register(uint16_t handle, uint32_t offset, const uint8_t* data, uint8_t len);
    void set_report_mode(uint16_t handle, uint8_t mode, bool cont);
  private:
    wiimote_callback_t _wiimote_callback;
};

#endif
