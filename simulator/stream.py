"""Project Sentinel event simulator.

Based on the reference generator in the Monitex brief. Additions:
  * one shared stream broadcast to every connected client
  * bursts on demand (press Enter) or on a timer (--burst-every)
  * optional malformed messages (--junk) to exercise validation

Run:  python simulator/stream.py            (reference behaviour)
      python simulator/stream.py --junk 0.05 --burst-every 45
"""
import argparse
import asyncio
import datetime
import json
import random
import threading
import uuid

import websockets

TYPES = ["motion_detected", "perimeter_breach", "door_forced", "glass_break",
         "smoke_detected", "fire_alarm", "object_detected", "loitering",
         "camera_offline", "sensor_fault", "panic_button"]
CAMERA = {"motion_detected", "object_detected", "loitering", "glass_break"}
ZONES = ["north-perimeter", "lobby", "loading-dock", "roof", "server-room"]

clients = set()
last_message = None


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_event():
    t = random.choice(TYPES)
    return {
        "event_id": "evt_" + uuid.uuid4().hex[:10],
        "site_id": f"site-{random.randint(100, 106)}",
        "zone": random.choice(ZONES),
        "type": t,
        "source": "camera" if t in CAMERA else "sensor",
        "confidence": round(random.uniform(0.35, 0.99), 2),
        "timestamp": now_iso(),
        "snapshot_url": None,
        "metadata": {"object": random.choice(["person", "vehicle", "animal"])}
                    if t == "object_detected" else {},
    }


def make_junk(previous):
    """One malformed message, the kind a real field feed sends."""
    evt = make_event()
    kind = random.choice(["drop_fields", "bad_confidence", "unknown_type",
                          "bad_timestamp", "not_json", "duplicate"])
    if kind == "drop_fields":
        for key in random.sample(["site_id", "zone", "confidence", "timestamp", "source"], 2):
            evt.pop(key)
    elif kind == "bad_confidence":
        evt["confidence"] = random.choice(["high", 1.7, -0.2, None])
    elif kind == "unknown_type":
        evt["type"] = "alien_invasion"
    elif kind == "bad_timestamp":
        evt["timestamp"] = "yesterday-ish"
    elif kind == "not_json":
        return '{"event_id": "evt_broken", "type": '
    elif kind == "duplicate" and previous:
        return previous
    return json.dumps(evt)


def next_message(junk_rate):
    global last_message
    if random.random() < junk_rate:
        msg = make_junk(last_message)
    else:
        msg = json.dumps(make_event())
    last_message = msg
    return msg


async def handler(ws):
    clients.add(ws)
    print(f"client connected ({len(clients)} total)")
    try:
        await ws.wait_closed()
    finally:
        clients.discard(ws)
        print(f"client disconnected ({len(clients)} total)")


async def produce(args):
    while True:
        websockets.broadcast(clients, next_message(args.junk))
        await asyncio.sleep(random.uniform(0.15, 2.0))   # bursty, as in the reference


async def burst(size, junk_rate):
    print(f">>> burst: {size} events at once")
    for _ in range(size):
        websockets.broadcast(clients, next_message(junk_rate))


async def burst_timer(args):
    while True:
        await asyncio.sleep(args.burst_every)
        await burst(args.burst_size, args.junk)


def watch_keyboard(loop, args):
    """Enter in this terminal fires a burst. Handy while recording the demo."""
    while True:
        try:
            input()
        except EOFError:
            return
        asyncio.run_coroutine_threadsafe(burst(args.burst_size, args.junk), loop)


def parse_args():
    p = argparse.ArgumentParser(description="Project Sentinel event simulator")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--junk", type=float, default=0.0,
                   help="share of malformed messages, 0.0-1.0 (default 0)")
    p.add_argument("--burst-size", type=int, default=200)
    p.add_argument("--burst-every", type=float, default=0,
                   help="seconds between automatic bursts (0 = off)")
    p.add_argument("--seed", type=int, help="fixed random seed for repeatable runs")
    return p.parse_args()


async def main():
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    loop = asyncio.get_running_loop()
    threading.Thread(target=watch_keyboard, args=(loop, args), daemon=True).start()
    async with websockets.serve(handler, args.host, args.port):
        print(f"Event stream live on ws://{args.host}:{args.port}  "
              f"(press Enter for a burst of {args.burst_size})")
        tasks = [produce(args)]
        if args.burst_every:
            tasks.append(burst_timer(args))
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("simulator stopped")
