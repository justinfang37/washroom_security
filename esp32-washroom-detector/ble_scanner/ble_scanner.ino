// ============================================================
//  BLE Device Detector  -  Step 1: just detect signals
//  Flash this to BOARD 2 (the "Bluetooth" board).
//
//  It scans for nearby Bluetooth Low Energy devices and lists
//  each one: MAC address + signal strength + name (if given).
//  No classification yet - that comes in a later step.
// ============================================================

#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

#define SCAN_SECONDS 5      // length of each scan pass

BLEScan* scanner;

// Called once per BLE device found during a scan.
class FoundCallback : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) override {
    Serial.printf("%s  RSSI=%4d  %s\n",
      d.getAddress().toString().c_str(),
      d.getRSSI(),
      d.haveName() ? d.getName().c_str() : "(no name)");
  }
};

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nBLE Device Detector starting...");

  BLEDevice::init("");
  scanner = BLEDevice::getScan();
  scanner->setAdvertisedDeviceCallbacks(new FoundCallback());
  scanner->setActiveScan(true);   // asks devices for names; uses a bit more power
  scanner->setInterval(100);
  scanner->setWindow(99);
}

void loop() {
  Serial.println("\n================ BLE scan ================");
  Serial.println("MAC                RSSI  name");
  scanner->start(SCAN_SECONDS, false);
  scanner->clearResults();        // free memory between passes
  Serial.println("---- scan complete ----");
  delay(500);
}
