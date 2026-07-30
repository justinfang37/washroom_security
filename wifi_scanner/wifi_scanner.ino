// ============================================================
//  WiFi Device Detector  -  Step 1: just detect signals
//  Flash this to BOARD 1 (the "WiFi" board).
//
//  It passively listens on 2.4 GHz WiFi, channel-hopping, and
//  lists every device it hears: MAC address + signal strength.
//  No classification yet - that comes in a later step.
// ============================================================

#include <WiFi.h>
#include "esp_wifi.h"

// ----- Settings you can tweak -----
#define HOP_INTERVAL    250     // ms spent listening on each channel
#define PRINT_INTERVAL  3000    // ms between printed device tables
#define FORGET_AFTER    30000   // ms: drop a device if unseen this long
#define MAX_DEVICES     100     // max devices tracked at once

// Common 2.4 GHz channels. Add 2,3,4,5,7,8,9,10,12,13 for a fuller sweep
// (more thorough, but slower to revisit each channel).
const uint8_t channels[] = {1, 6, 11};
const int NUM_CHANNELS = sizeof(channels) / sizeof(channels[0]);

// ----- One tracked device -----
struct Device {
  uint8_t  mac[6];
  int8_t   rssi;       // signal strength, dBm (closer to 0 = closer/stronger)
  uint8_t  channel;
  uint32_t count;      // how many packets we've heard from it
  uint32_t lastSeen;   // millis() of last packet
  bool     used;
};

Device devices[MAX_DEVICES];
int channelIdx = 0;

int findDevice(const uint8_t* mac) {
  for (int i = 0; i < MAX_DEVICES; i++)
    if (devices[i].used && memcmp(devices[i].mac, mac, 6) == 0) return i;
  return -1;
}

int addDevice(const uint8_t* mac) {
  for (int i = 0; i < MAX_DEVICES; i++)
    if (!devices[i].used) {
      devices[i] = {};
      devices[i].used = true;
      memcpy(devices[i].mac, mac, 6);
      return i;
    }
  return -1;  // table full
}

// Called for every WiFi packet the radio hears.
void onPacket(void* buf, wifi_promiscuous_pkt_type_t type) {
  const wifi_promiscuous_pkt_t* pkt = (wifi_promiscuous_pkt_t*)buf;
  if (pkt->rx_ctrl.sig_len < 16) return;      // too short to hold a sender MAC

  const uint8_t* txMac = pkt->payload + 10;   // addr2 = transmitter address
  int i = findDevice(txMac);
  if (i < 0) i = addDevice(txMac);
  if (i < 0) return;                          // table full, skip

  devices[i].rssi     = pkt->rx_ctrl.rssi;
  devices[i].channel  = pkt->rx_ctrl.channel;
  devices[i].count++;
  devices[i].lastSeen = millis();
}

void printTable() {
  uint32_t now = millis();
  int shown = 0;

  Serial.println("\n================ WiFi devices seen ================");
  Serial.println("MAC                RSSI  ch   pkts   age");
  for (int i = 0; i < MAX_DEVICES; i++) {
    if (!devices[i].used) continue;
    if (now - devices[i].lastSeen > FORGET_AFTER) { devices[i].used = false; continue; }

    uint8_t* m = devices[i].mac;
    Serial.printf("%02X:%02X:%02X:%02X:%02X:%02X  %4d  %2d  %5lu   %lus\n",
      m[0], m[1], m[2], m[3], m[4], m[5],
      devices[i].rssi, devices[i].channel, devices[i].count,
      (now - devices[i].lastSeen) / 1000);
    shown++;
  }
  Serial.printf("---- %d device(s) currently in range ----\n", shown);
}

uint32_t lastHop = 0, lastPrint = 0;

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nWiFi Device Detector starting (2.4 GHz, passive)...");

  WiFi.mode(WIFI_MODE_NULL);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(&onPacket);
  esp_wifi_set_channel(channels[0], WIFI_SECOND_CHAN_NONE);
}

void loop() {
  uint32_t now = millis();

  if (now - lastHop > HOP_INTERVAL) {
    lastHop = now;
    channelIdx = (channelIdx + 1) % NUM_CHANNELS;
    esp_wifi_set_channel(channels[channelIdx], WIFI_SECOND_CHAN_NONE);
  }

  if (now - lastPrint > PRINT_INTERVAL) {
    lastPrint = now;
    printTable();
  }
}
