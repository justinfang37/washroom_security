# Final state after the competition

Hey Justin — this is everything from my side, brought up to what we actually
demoed. **Your files are untouched**: `wifi_scanner/`, `ble_scanner/` and
`README.md` are exactly as you left them. The only things I changed are two
lines-worth of behaviour in your dashboard, both described below.

Everything also lives at
[DavidWang1231/WashroomSweep](https://github.com/DavidWang1231/WashroomSweep)
if you'd rather pull from there.

## The one thing to know

**Your dashboard couldn't run in this repo.** `monitor.py` loads the
correlation maths from `host/sweep.py` at startup, and documents
`softap_demo.ino` as its board firmware — neither existed here, so `SWEEP`
resolved to `None` and the sweep button returned "host/sweep.py not found".
Both files are in this branch now, so it works as you wrote it.

## What's new

| Folder | What it is |
|---|---|
| `wifi_sniffer/` | The detector. Byte counting per device, uplink/downlink split, 200 ms windows, CSV + heartbeat over serial. |
| `softap_demo/` | The board hosts its own 802.11n network while sniffing it. This is what got us a live detection — see below. It also finds the camera on its own now, so no laptop command is needed mid-demo. |
| `host/sweep.py` | The correlation analysis your dashboard imports. |
| `ble_presence/` | A portable variant of your BLE scanner — see the compile note below. |
| `slides/` | The deck we presented (PDF, PPTX, HTML). |
| `docs/dashboard.png` | Screenshot of your dashboard with a real capture replayed through it. |

## Two changes to your dashboard

**1. A live alert banner.** The asymmetry signal was already being collected,
but it only appeared inside a device's expanded drawer, and the red CANDIDATE
styling only fired after a 30 s sweep finished. So opening a camera in front of
the dashboard changed nothing visible — we hit this during rehearsal. There's
now a banner that fires as soon as a device sustains video-scale upload with
little or nothing coming back, using the same thresholds as `sweep.py`'s
asymmetry stage so the banner and the verdict can't disagree. It names the light
sweep as the confirming step rather than implying the room is clear.

**2. Renamed the RSSI buckets.** `IN-ROOM / near / wall / far` became
`strong / medium / weak / faint`, same thresholds. The old labels assert a
location, and our own stated position is that RSSI is not distance and we don't
localize — a judge reading the screen next to that claim would have caught it.
The column header moved from "Distance" to "Level" to match.

## Things I measured that are worth having written down

**The ESP32 can't see 802.11ax.** Against a modern phone hotspot serving a
laptop, a **6.6 MB/s** download on 2.4 GHz channel 6 came back to the sniffer as
**~2 KB/s — 0.03%**. The receive path was verified healthy at the same moment:
the driver reported `channel=6` and beacons arrived at the correct 100 ms
cadence. Counting FCS-failed frames as an airtime proxy didn't help either
(415 KB/s idle vs 402 KB/s during the download — that figure is ambient noise,
not our link). No software fixes this; hence `softap_demo/`, which forces
clients onto 802.11n. Cheap IP cameras are typically 802.11n, so the intended
target is still in range.

**Live result:** 17.9 MB uplink / 0 downlink over 30 s — 99.9% of all air
traffic, three orders of magnitude above every other client.

**The promiscuous filter matters, and your version had it right.** When I
rewrote the sniffer I dropped your `esp_wifi_set_promiscuous_filter(MGMT|DATA)`.
Without it the driver also delivers FCS-failed frames, which near a busy AP are
constant and carry effectively random header bytes — I measured a near-uniform
spread across all eight ToDS/FromDS combinations where real traffic sits in two.
Those junk frames mint random MACs that flood the device table and evict real
stations before they're reported. Restoring your line fixed it.

## Two notes on `ble_scanner/`

Both found while compiling it, neither changed in your file:

- **It needs the Huge APP partition scheme.** At the default it's 124% of flash
  and won't build; with Huge APP it's 51%. Tools > Partition Scheme in the IDE.
- **It builds only for classic ESP32.** `BLE_ADDR_TYPE_RANDOM` /
  `BLE_ADDR_TYPE_RPA_RANDOM` don't exist on the C3/S3 BLE stack. `ble_presence/`
  compares the raw address-type byte instead and builds on all three — take that
  fix into yours if you want C3/S3 support. Note it also catches address type 2
  (resolvable-private), which the original misses.

## What we didn't get working

The light-stimulus correlation never closed over the air. Six attempts, each
blocked by a different property of using a phone as the camera: the app streams
constant-bitrate by default; auto-gain turns a dark scene into a noisy
full-bitrate image so the bitrate sometimes went *up*; and it composites a
mandatory front+rear pair, so the front sensor held the floor at ~430 KB/s no
matter what we did to the rear lens. MJPEG mode did confirm the mechanism —
fully occluding the lens dropped the stream from ~700 KB/s to ~1 KB — but a
clean square wave was unreachable.

A valid stand-in needs fixed exposure, a single sensor, and VBR encoding, i.e.
an actual IP camera. That's the one purchase that would move this forward.

## One bench gotcha

Rapidly opening and closing the serial port yanks DTR/RTS and can drop the board
into a reset loop — I chased phantom data corruption for a while before working
that out. Give it ~2 s after opening before sending anything. `sweep.py` and
`monitor.py` both do.
