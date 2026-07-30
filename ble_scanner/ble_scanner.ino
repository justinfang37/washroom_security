// ============================================================
//  BLE Device Detector  -  Step 2: detect + classify
//  Flash this to BOARD 2 (the "Bluetooth" board).
//
//  Scans for Bluetooth Low Energy devices and, for each one,
//  shows: how close it is, its name (if broadcast), its maker
//  (from the advertised manufacturer ID), and whether its
//  address is randomized/private.
//
//  Columns mirror the WiFi scanner so the mental model matches:
//    RSSI / dist  -> where it is
//    name / maker -> what it is
//    priv         -> real address (lookup-able) vs randomized
//    seen         -> how many times we've spotted it (persistence)
// ============================================================

#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

#define SCAN_SECONDS 5       // length of each scan pass
#define MAX_DEVICES  120     // max devices remembered at once
#define FORGET_AFTER 60000   // ms: drop a device if unseen this long

struct BleDev {
  char     addr[18];
  int      rssi;
  char     name[24];
  char     maker[16];
  bool     randomAddr;   // true = private/randomized address
  uint32_t seen;         // how many advertisements we've caught
  uint32_t lastSeen;
  bool     used;
};

BleDev devices[MAX_DEVICES];
BLEScan* scanner;

// A few common Bluetooth SIG company IDs. Extend from the official
// "Company Identifiers" list if you want to name more makers.
const char* makerName(uint16_t id) {
  switch (id) {
    case 0x004C: return "Apple";
    case 0x0006: return "Microsoft";
    case 0x0075: return "Samsung";
    case 0x00E0: return "Google";
    case 0x0087: return "Garmin";
    case 0x0059: return "Nordic";
    case 0x009E: return "Bose";
    case 0x00D7: return "Qualcomm";
    default:     return "";
  }
}

const char* proximity(int rssi) {
  if (rssi > -50) return "IN-ROOM";
  if (rssi > -70) return "near";
  if (rssi > -82) return "wall";
  return "far";
}

int findDevice(const char* addr) {
  for (int i = 0; i < MAX_DEVICES; i++)
    if (devices[i].used && strcmp(devices[i].addr, addr) == 0) return i;
  return -1;
}
int addDevice(const char* addr) {
  for (int i = 0; i < MAX_DEVICES; i++)
    if (!devices[i].used) {
      devices[i] = {};
      devices[i].used = true;
      strncpy(devices[i].addr, addr, 17);
      return i;
    }
  return -1;
}

// Called once per advertisement heard during a scan.
class FoundCallback : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) override {
    String a = d.getAddress().toString();
    int i = findDevice(a.c_str());
    if (i < 0) i = addDevice(a.c_str());
    if (i < 0) return;

    devices[i].rssi = d.getRSSI();
    devices[i].lastSeen = millis();
    devices[i].seen++;

    uint8_t t = d.getAddressType();
    devices[i].randomAddr = (t == BLE_ADDR_TYPE_RANDOM || t == BLE_ADDR_TYPE_RPA_RANDOM);

    if (d.haveName())
      strncpy(devices[i].name, d.getName().c_str(), 23);

    if (d.haveManufacturerData()) {
      String md = d.getManufacturerData();
      if (md.length() >= 2) {
        uint16_t id = (uint8_t)md[0] | ((uint8_t)md[1] << 8);  // little-endian
        const char* v = makerName(id);
        if (v[0]) strncpy(devices[i].maker, v, 15);
        else      snprintf(devices[i].maker, 15, "0x%04X", id);
      }
    }
  }
};

void printTable() {
  uint32_t now = millis();

  int idx[MAX_DEVICES];
  int n = 0;
  for (int i = 0; i < MAX_DEVICES; i++) {
    if (!devices[i].used) continue;
    if (now - devices[i].lastSeen > FORGET_AFTER) { devices[i].used = false; continue; }
    idx[n++] = i;
  }

  // Sort strongest (closest) first.
  for (int a = 0; a < n; a++)
    for (int b = a + 1; b < n; b++)
      if (devices[idx[b]].rssi > devices[idx[a]].rssi) {
        int t = idx[a]; idx[a] = idx[b]; idx[b] = t;
      }

  Serial.println("\n============ BLE devices (closest first) ============");
  Serial.println("ADDRESS            RSSI  dist     priv  seen  maker      name");
  for (int k = 0; k < n; k++) {
    BleDev& d = devices[idx[k]];
    Serial.printf("%-17s  %4d  %-7s  %-4s  %4lu  %-9s  %s\n",
                  d.addr, d.rssi, proximity(d.rssi),
                  d.randomAddr ? "rnd" : "-",
                  d.seen,
                  d.maker[0] ? d.maker : "-",
                  d.name[0] ? d.name : "");
  }
  Serial.printf("---- %d BLE device(s) in range ----\n", n);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nBLE Device Detector starting...");

  BLEDevice::init("");
  scanner = BLEDevice::getScan();
  scanner->setAdvertisedDeviceCallbacks(new FoundCallback());
  scanner->setActiveScan(true);   // ask devices for names (uses a bit more power)
  scanner->setInterval(100);
  scanner->setWindow(99);
}

void loop() {
  scanner->start(SCAN_SECONDS, false);
  scanner->clearResults();        // free the library's buffer; our table persists
  printTable();
  delay(200);
}
