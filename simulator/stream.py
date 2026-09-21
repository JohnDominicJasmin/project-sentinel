import argparse
import asyncio
import datetime
import json
import random
import threading
import uuid
from collections import deque
from urllib.parse import parse_qs, urlparse

import websockets

TYPES = ["motion_detected", "perimeter_breach", "door_forced", "glass_break",
         "smoke_detected", "fire_alarm", "object_detected", "loitering",
         "camera_offline", "sensor_fault", "panic_button"]
CAMERA = {"motion_detected", "object_detected", "loitering", "glass_break"}
ZONES = ["north-perimeter", "lobby", "loading-dock", "roof", "server-room"]

clients = set()
last_message = None
history = deque(maxlen=5000)


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


def send(message):
    history.append((event_id_of(message), message))
    websockets.broadcast(clients, message)


def event_id_of(message):
    try:
        return json.loads(message).get("event_id")
    except (ValueError, AttributeError):
        return None


def missed_since(since):
    items = list(history)
    for index, (event_id, _) in enumerate(items):
        if event_id == since:
            return [message for _, message in items[index + 1:]]
    return [message for _, message in items]


async def handler(ws):
    since = parse_qs(urlparse(ws.request.path).query).get("since", [None])[0]
    missed = missed_since(since) if since else []
    clients.add(ws)
    print(f"client connected ({len(clients)} total)")
    if missed:
        print(f">>> replaying {len(missed)} missed events after {since}")
    try:
        for message in missed:
            await ws.send(message)
        await ws.wait_closed()
    finally:
        clients.discard(ws)
        print(f"client disconnected ({len(clients)} total)")


async def produce(args):
    while True:
        send(next_message(args.junk))
        await asyncio.sleep(random.uniform(0.15, 2.0))


async def burst(size, junk_rate):
    print(f">>> burst: {size} events at once")
    for _ in range(size):
        send(next_message(junk_rate))


async def break_in(site, zone):
    print(f">>> scripted break-in at {site} / {zone}")
    for kind, confidence in (("door_forced", 0.93), ("perimeter_breach", 0.88), ("glass_break", 0.91)):
        event = make_event()
        event.update(type=kind, source="sensor", site_id=site, zone=zone, confidence=confidence, metadata={})
        send(json.dumps(event))
        await asyncio.sleep(1.5)


async def burst_timer(args):
    while True:
        await asyncio.sleep(args.burst_every)
        await burst(args.burst_size, args.junk)


def watch_keyboard(loop, args):
    while True:
        try:
            line = input().strip().lower()
        except EOFError:
            return
        if line == "b":
            job = break_in(args.scenario_site, args.scenario_zone)
        else:
            job = burst(args.burst_size, args.junk)
        asyncio.run_coroutine_threadsafe(job, loop)


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
    p.add_argument("--scenario-site", default="site-101", help="site used by the scripted break-in")
    p.add_argument("--scenario-zone", default="lobby", help="zone used by the scripted break-in")
    return p.parse_args()


async def main():
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    loop = asyncio.get_running_loop()
    threading.Thread(target=watch_keyboard, args=(loop, args), daemon=True).start()
    async with websockets.serve(handler, args.host, args.port):
        print(f"Event stream live on ws://{args.host}:{args.port}  "
              f"(Enter: burst of {args.burst_size} | b + Enter: break-in at {args.scenario_site}/{args.scenario_zone})")
        tasks = [produce(args)]
        if args.burst_every:
            tasks.append(burst_timer(args))
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("simulator stopped")
