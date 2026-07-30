# ESP32 Washroom Device Detector

Two ESP32 boards that passively detect nearby wireless devices in a private space,
as the foundation of a hidden-camera / covert-recording detector.

## Step 1 (this stage): just detect signals

- `wifi_scanner/`  -> flash to Board 1. Lists nearby WiFi devices (MAC + signal strength).
- `ble_scanner/`   -> flash to Board 2. Lists nearby Bluetooth (BLE) devices (MAC + signal).

Right now they ONLY detect and list devices. No classification, no upload detection yet.
That comes in later steps once we confirm both boards see what's around you.

In Arduino IDE: Tools → Partition Scheme → "Huge APP (3MB No OTA/1MB SPIFFS)" for ble_scanner

## What each column means

WiFi output:  MAC, RSSI (dBm), channel, packet count, seconds-since-seen
BLE output:   MAC, RSSI (dBm), name (if the device advertises one)

RSSI is signal strength in dBm. Closer to 0 = stronger/closer.
  e.g. -40 = very close,  -70 = across the room,  -85 = far/weak.

## How to upload (Arduino IDE)

1. Install the ESP32 board package:
   File > Preferences > "Additional Boards Manager URLs", add:
     https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   Then Tools > Board > Boards Manager > search "esp32" > install.
2. Open wifi_scanner/wifi_scanner.ino (or ble_scanner/ble_scanner.ino).
3. Tools > Board > select your board (e.g. "ESP32 Dev Module").
4. Tools > Port > pick the port your board shows up on.
5. Click Upload.
6. Open Tools > Serial Monitor, set baud to 115200, and watch the devices appear.

## Notes / expectations

- Classic ESP32 sees 2.4 GHz WiFi only (not 5 GHz).
- Modern phones randomize their MAC, so one phone may show as several MACs. Normal.
- A device that stays put with a steady MAC and steady signal is the interesting one.

## Next steps (later)

- Add traffic + uplink tracking to the WiFi board -> flag heavy uploaders (cameras).
- Stream both boards to your phone hotspot / laptop to aggregate + localize.
- Manual light-fluctuation test as final confirmation (streaming vs scrolling).
