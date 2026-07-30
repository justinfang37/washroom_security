#!/usr/bin/env python3
"""
Live dashboard for the washroom detector.

Two-board setup:

  BOARD 1  David's softap_demo.ino
           Hosts the WiFi network AND sniffs it. Talks CSV over USB serial:
               WINDOW,<ts_ms>,<interval_ms>,<active>
               <ts_ms>,<mac>,<up_bytes>,<down_bytes>,<up_pkts>,<down_pkts>,<rssi>
           His rows are per-window deltas (~200ms), so this script adds them up
           and derives a live bytes/sec rate.

  BOARD 2  your ble_scanner.ino
           Joins his network and reports BLE devices over UDP (wireless).

Both feeds land in one dashboard.

USAGE
    python3 monitor.py               # normal: USB boards + wireless, both
    python3 monitor.py --no-serial   # skip USB, so you can reflash a board
    python3 monitor.py --port /dev/cu.usbserial-0001    # one specific board

    Then open http://localhost:8080  (opens automatically)

REQUIREMENTS
    pip3 install pyserial      (only needed for USB; wireless works without it)

NOTE
    Only one program can hold a serial port at a time -- so this and David's
    sweep.py cannot both read his board at once. Run one or the other. Same
    goes for uploading a sketch: stop this first, or start it --no-serial.
"""

import argparse
import json
import re
import socket
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# pyserial is only needed for USB mode, so don't hard-fail without it.
try:
    import serial
    from serial.tools import list_ports
    HAVE_SERIAL = True
except ImportError:
    HAVE_SERIAL = False

BAUD = 115200
STALE_AFTER = 60.0      # seconds without an update before we drop a device
HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- parsing

# WiFi row:  MAC  RSSI  dist  ch  kind  priv  frames  data
WIFI_ROW = re.compile(
    r"^([0-9A-Fa-f:]{17})\s+(-?\d+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s*$"
)
# BLE row:   ADDRESS  RSSI  dist  priv  seen  maker  [name]
BLE_ROW = re.compile(
    r"^([0-9A-Fa-f:]{17})\s+(-?\d+)\s+(\S+)\s+(\S+)\s+(\d+)\s+(\S+)\s*(.*)$"
)
# WiFi footer:  ---- 14 device(s) | 147 raw frames heard (now on ch 6) ----
WIFI_FOOTER = re.compile(r"(\d+)\s+device\(s\).*?(\d+)\s+raw frames")

# --- David's board (softap_demo / wifi_sniffer_v2) speaks CSV over serial ---
#   heartbeat : WINDOW,<ts_ms>,<interval_ms>,<active_devices>
#   per device: <ts_ms>,<mac>,<up_bytes>,<down_bytes>,<up_pkts>,<down_pkts>,<rssi>
# His rows are PER-WINDOW deltas (~200 ms), not running totals, so we add them
# up ourselves and also derive a live bytes/sec rate.
DAVID_ROW = re.compile(
    r"^(\d+),([0-9A-Fa-f:]{17}),(\d+),(\d+),(\d+),(\d+),(-?[\d.]+)\s*$"
)
DAVID_WINDOW = re.compile(r"^WINDOW,(\d+)")
DAVID_MARK = re.compile(r"^MARK,(\d+)")

RATE_WINDOW = 3.0   # seconds of history used for the bytes/sec figure

devices = {}        # key -> record shown in the UI
accum = {}          # key -> running totals + recent samples, for David's deltas
meta = {"wifi_frames": 0, "ports": {}, "windows": 0, "last_mark": None}
lock = threading.Lock()


def proximity(rssi):
    """Same buckets the boards use, for data that arrives as raw RSSI."""
    if rssi > -50:
        return "IN-ROOM"
    if rssi > -70:
        return "near"
    if rssi > -82:
        return "wall"
    return "far"


def upsert(key, fields):
    """Insert or update a device, tracking how its signal is trending."""
    now = time.time()
    with lock:
        rec = devices.get(key)
        if rec is None:
            rec = {"key": key, "first_seen": now, "trend": 0, "prev_rssi": fields["rssi"]}
            devices[key] = rec
        else:
            # Compare against the reading from ~2s ago to get a stable trend.
            if now - rec.get("trend_at", 0) > 2.0:
                delta = fields["rssi"] - rec["prev_rssi"]
                rec["trend"] = 1 if delta >= 4 else (-1 if delta <= -4 else 0)
                rec["prev_rssi"] = fields["rssi"]
                rec["trend_at"] = now
        rec.update(fields)
        rec["last_seen"] = now


def handle_david_row(mac, up, down, uppkts, downpkts, rssi):
    """One 200 ms window from David's board: accumulate totals, compute rate."""
    key = "wifi:" + mac.upper()
    now = time.time()

    with lock:
        a = accum.setdefault(key, {"up": 0, "down": 0, "uppkts": 0,
                                   "downpkts": 0, "samples": deque()})
        a["up"] += up
        a["down"] += down
        a["uppkts"] += uppkts
        a["downpkts"] += downpkts

        s = a["samples"]
        s.append((now, up, down))
        while s and now - s[0][0] > RATE_WINDOW:
            s.popleft()
        span = (now - s[0][0]) if len(s) > 1 else RATE_WINDOW
        span = max(span, 0.5)
        up_rate = sum(x[1] for x in s) / span
        down_rate = sum(x[2] for x in s) / span
        totals = dict(a)

    rssi_i = int(round(rssi))
    upsert(key, {
        "source": "wifi",
        "mac": mac.upper(),
        "rssi": rssi_i,
        "dist": proximity(rssi_i),
        "channel": 0,               # his CSV doesn't carry the channel
        "kind": "device",
        # locally-administered bit => randomized/private MAC
        "priv": bool(int(mac.split(":")[0], 16) & 0x02),
        "frames": totals["uppkts"] + totals["downpkts"],
        "up": totals["up"],
        "down": totals["down"],
        "uppkts": totals["uppkts"],
        "downpkts": totals["downpkts"],
        "up_rate": int(up_rate),
        "down_rate": int(down_rate),
    })


def handle_line(line, state):
    """Feed one line of serial output through the parser."""
    line = line.rstrip()
    if not line:
        return

    # ---- David's board: comma-separated, so it can't be confused with the
    # space-aligned tables our own sketches print. ----
    if line.startswith("#") or line.startswith("ts_ms,"):
        return                                  # his config echoes / CSV header
    m = DAVID_WINDOW.match(line)
    if m:
        with lock:
            meta["windows"] += 1
            meta["ports"][state.get("port", "serial")] = "connected (David's board)"
        return
    m = DAVID_MARK.match(line)
    if m:
        with lock:
            meta["last_mark"] = int(m.group(1))
        return
    m = DAVID_ROW.match(line)
    if m:
        ts, mac, up, down, uppkts, downpkts, rssi = m.groups()
        handle_david_row(mac, int(up), int(down),
                         int(uppkts), int(downpkts), float(rssi))
        return

    # Table headers tell us which board / which format follows.
    if "WiFi devices" in line:
        state["mode"] = "wifi"
        return
    if "BLE devices" in line:
        state["mode"] = "ble"
        return
    if line.startswith(("MAC ", "ADDRESS", "====")):
        return
    if line.startswith("----"):
        m = WIFI_FOOTER.search(line)
        if m:
            with lock:
                meta["wifi_frames"] = int(m.group(2))
        return

    if state["mode"] == "wifi":
        m = WIFI_ROW.match(line)
        if m:
            mac, rssi, dist, ch, kind, priv, up, down = m.groups()
            upsert("wifi:" + mac.upper(), {
                "source": "wifi",
                "mac": mac.upper(),
                "rssi": int(rssi),
                "dist": dist,
                "channel": int(ch),
                "kind": kind,
                "priv": priv == "rnd",
                "frames": 0,          # serial table doesn't carry a frame count
                "up": int(up),
                "down": int(down),
                "uppkts": 0,
                "downpkts": 0,
            })
    elif state["mode"] == "ble":
        m = BLE_ROW.match(line)
        if m:
            addr, rssi, dist, priv, seen, maker, name = m.groups()
            upsert("ble:" + addr.lower(), {
                "source": "ble",
                "mac": addr.lower(),
                "rssi": int(rssi),
                "dist": dist,
                "priv": priv == "rnd",
                "seen": int(seen),
                "maker": "" if maker == "-" else maker,
                "name": name.strip(),
            })


def reader(port):
    """Continuously read one serial port, reconnecting if it drops."""
    state = {"mode": None, "port": port}
    while True:
        try:
            with serial.Serial(port, BAUD, timeout=2) as ser:
                with lock:
                    meta["ports"][port] = "connected"
                buf = b""
                while True:
                    chunk = ser.read(256)
                    if chunk:
                        buf += chunk
                        while b"\n" in buf:
                            raw, buf = buf.split(b"\n", 1)
                            handle_line(raw.decode("utf-8", "replace"), state)
        except Exception as e:
            with lock:
                meta["ports"][port] = f"disconnected ({type(e).__name__})"
            time.sleep(2)


def udp_listener(udp_port):
    """Receive JSON reports broadcast by boards over the hotspot."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", udp_port))
    except OSError as e:
        with lock:
            meta["ports"][f"udp:{udp_port}"] = f"bind failed ({e.strerror})"
        return
    with lock:
        meta["ports"][f"udp:{udp_port}"] = "listening"

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            msg = json.loads(data.decode("utf-8", "replace"))
            src = msg.get("src")
            unit = msg.get("unit", addr[0])

            with lock:
                meta["ports"][f"udp:{udp_port}"] = f"listening ({unit})"
                if src == "wifi" and "frames" in msg:
                    meta["wifi_frames"] = msg["frames"]

            for d in msg.get("devices", []):
                if src == "wifi":
                    upsert("wifi:" + d["mac"].upper(), {
                        "source": "wifi",
                        "mac": d["mac"].upper(),
                        "rssi": d["rssi"],
                        "dist": d["dist"],
                        "channel": d["ch"],
                        "kind": d["kind"],
                        "priv": bool(d["priv"]),
                        "frames": d["frames"],
                        # up/down bytes: the upload figure is the camera signal
                        "up": d.get("up", 0),
                        "down": d.get("down", 0),
                        "uppkts": d.get("uppkts", 0),
                        "downpkts": d.get("downpkts", 0),
                    })
                elif src == "ble":
                    upsert("ble:" + d["mac"].lower(), {
                        "source": "ble",
                        "mac": d["mac"].lower(),
                        "rssi": d["rssi"],
                        "dist": d["dist"],
                        "priv": bool(d["priv"]),
                        "seen": d["seen"],
                        "maker": d.get("maker", ""),
                        "name": d.get("name", ""),
                    })
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            continue  # ignore malformed/truncated datagrams
        except Exception:
            time.sleep(0.5)


def autodetect():
    """Guess which serial ports are ESP32 boards."""
    if not HAVE_SERIAL:
        return []
    hits = []
    for p in list_ports.comports():
        d = p.device
        if any(t in d for t in ("usbserial", "usbmodem", "wchusb", "SLAB", "ttyUSB", "ttyACM")):
            hits.append(d)
    return hits


# ---------------------------------------------------------------- web server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # keep the console quiet

    def do_GET(self):
        if self.path.startswith("/api/devices"):
            now = time.time()
            with lock:
                for k in [k for k, r in devices.items() if now - r["last_seen"] > STALE_AFTER]:
                    del devices[k]
                    accum.pop(k, None)   # drop its running totals too
                payload = {
                    "devices": sorted(
                        [dict(r, age=round(now - r["last_seen"], 1),
                                 uptime=round(now - r["first_seen"]))
                         for r in devices.values()],
                        key=lambda r: -r["rssi"],
                    ),
                    "meta": dict(meta),
                }
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        page = (HERE / "dashboard.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", action="append", default=[],
                    help="serial port (repeatable); auto-detects if omitted")
    ap.add_argument("--http-port", type=int, default=8080)
    ap.add_argument("--udp-port", type=int, default=4210,
                    help="listen for wireless board reports on this port")
    ap.add_argument("--no-serial", action="store_true",
                    help="don't open any serial port -- use this while "
                         "reflashing a board, so the upload isn't blocked")
    args = ap.parse_args()

    # Serial is ON by default: David's board reports over USB, so the common
    # case should just work. Pass --no-serial to free the port for an upload.
    ports = [] if args.no_serial else (args.port or autodetect())

    if ports and not HAVE_SERIAL:
        sys.exit("Reading boards over USB needs pyserial. Run:\n"
                 "    pip3 install pyserial\n"
                 "(or start with --no-serial to run wireless-only)")
    if not args.no_serial and not HAVE_SERIAL:
        print("NOTE: pyserial isn't installed, so USB boards can't be read.")
        print("      pip3 install pyserial      (wireless still works)")

    print("Reading from:")
    for p in ports:
        print("   ", p, "(usb)")
        threading.Thread(target=reader, args=(p,), daemon=True).start()

    print(f"    UDP :{args.udp_port} (wireless)")
    threading.Thread(target=udp_listener, args=(args.udp_port,), daemon=True).start()

    if not ports:
        print("    (wireless only -- no serial ports opened; use --serial for USB)")

    url = f"http://localhost:{args.http_port}"
    print(f"\nDashboard: {url}   (Ctrl+C to stop)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        HTTPServer(("127.0.0.1", args.http_port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
