# Wiimote Bluetooth Connection Library for Arduino core for ESP32

This library provides C++ for connecting to and receiving data from Wiimotes and Wii Balance Boards. Controllers can be paired by passing through a manually triggered `scan()`, pressing the pair button on the device to generate a `WIIMOTE_EVENT_NEW` event, and finally `initiate_auth()` to save. After controllers are paired, they can be reconnected with only the A button or 1+2 buttons without the need for pairing. The example code demonstrates the flow shown below using a momentary button on GPIO pin 21.

## Connection Flow

```mermaid
graph TD
I[🛜 Init] --> P1[🔴 GPIO 21 Pair Button] --> S[🫱 Scan] --> P2[🔴 Wiimote Pair Button] --> N[❇️ New Connection] --> A[🤝 Auth] --> L[📝 Add To Whitelist]
I --> B[🔘A Button] --> T[❇️ Temp Connection] --> Q{📋 Check Whitelist} --pass--> C
Q --fail--> D[❌ Disconnect]
A --> C[✅ Connected]
S --timeout--> O[✋ Stop Scan]
C-->O
C--power off-->D
P1--disconnect all-->D
```

### Duck Hunt fork

This copy is patched for the Duck Hunt light gun. On top of the upstream library:

- `enable_ir()` and the granular `ir_send_report()` / `ir_write_register()` /
  `set_report_mode()` steps — the IR camera and report 0x33 with four dots.
- `read_rssi()` / `read_link_quality()` and their events, for telling a weak
  signal apart from interference when the report rate sags.
- `set_pin_source()`. The remote asks for a different PIN depending on which
  button made it discoverable: the red SYNC button wants the *host's* bluetooth
  address (LSB first) and makes the remote store the host, while **1+2** wants
  the *remote's own* address and stores nothing. Upstream only ever answers with
  the host's, so a 1+2 press fails authentication and the remote hangs up.
- `WIIMOTE_EVENT_AUTH_COMPLETE`, so the sketch can see that failure and try the
  other PIN instead of guessing.
- `connect(bd_addr)`, which pages a known remote directly instead of waiting for
  an inquiry to rediscover it — an inquiry only finds a remote inside its ~20 s
  discoverable window, paging reaches one that is merely awake. A page that times
  out (an asleep or absent remote) is now dropped cleanly; before, the failed
  connection's handle was used for L2CAP anyway.
- `get_address(handle)`, so the sketch can remember which remote that was.

### Notes

1. Pairing is only stored on the wiimote when using the red-sync button, pairing by pressing 1 & 2 is not saved.
2. Reconnecting a paired device is easier when scanning is off.
3. Scanning for new devices is harder when other devices are still connected, hence the need to disconnect all devices before starting.
4. The maximum number of remotes that can be connected is 4 after they have been paired.

## Interpreting Data

This library does not do all of the work of interpreting the data that streams from the wiimotes & balance boards, but the example does show how to get started with some common uses. More information is found at the references below.

### References

- https://wiibrew.org/wiki/Wiimote
  - https://wiibrew.org/wiki/Wiimote/Extension_Controllers
  - https://wiibrew.org/wiki/Wii_Balance_Board
- http://www.yts.rdy.jp/pic/GB002/GB002.html
  - http://www.yts.rdy.jp/pic/GB002/hcip.html
  - http://www.yts.rdy.jp/pic/GB002/hcic.html
  - http://www.yts.rdy.jp/pic/GB002/l2cap.html
- https://qiita.com/jp-96/items/ff3822ab81f7696172c0
- https://www.wdic.org/w/WDIC/Bluetooth
  - https://www.wdic.org/w/WDIC/HCI%20%28Bluetooth%29
  - https://www.wdic.org/w/WDIC/L2CAP
