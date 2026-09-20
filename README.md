# Project Sentinel

A miniature real-time alarm monitoring service. It ingests a live stream of sensor and camera events, triages each one with an LLM, and puts them in front of an operator on a live dashboard ranked by urgency.

**Demo video:** TODO_DEMO_LINK

## What it does

| The requirement | Where it lives | The short version |
|---|---|---|
| 1. Ingest a bursty stream without blocking, dropping or crashing | `stream_client.py`, `pipeline.py`, `normalize.py` | One async consumer, repair-or-reject validation, dedupe by event id, auto-reconnect with capped backoff |
| 2. A video worker off the hot path | `camera/` | A separate OS process runs YOLO26n; only the newest frame is ever analysed |
| 3. LLM triage per event | `triage/` | Background workers, priority queue, batching, schema-validated output, rules as the floor and the fallback |
| 4. A live dashboard ranked by severity, with acknowledge and resolve | `hub.py`, `frontend/` | Snapshot plus sequence-numbered deltas over one WebSocket, no polling, no manual refresh |
| 5. Alerting on criticals and escalation on patterns | `useCriticalAlerts.ts`, `escalation.py` | Sticky banner, tab title, tone, and a correlator that folds repeated or corroborated signals into one incident |

On top of the five, three stretch goals: **correlation and escalation**, **AI cost and latency metrics**, and **persistence** so nothing is lost across a crash.

Deliberately not built: deeper vision (zone and tripwire rules, frame captioning), per-site history views, the operator feedback loop, and dashboard auth. They are in "What I would build next".

## Architecture

```
  simulator/stream.py                     camera worker (separate OS process)
  ws://localhost:8765                     decode -> YOLO26n ONNX -> tracker
  bursty | junk | replay via ?since=      newest frame only, 4 fps
          |                                            |
          | WebSocket, auto-reconnect                  | multiprocessing.Queue
          v                                            v
  stream_client.py                                camera/bridge.py
          |                                            |
          +---------------------+----------------------+
                                |
                                v
                  +---------------------------------+
                  |        pipeline.submit()        |   the only way in
                  |  parse -> normalize -> dedupe   |
                  |  -> rule severity -> store      |
                  +----------------+----------------+
                                   |  listeners
              +--------------------+--------------------+
              v                    v                    v
         store.py            triage/service.py     escalation.py
      in-memory truth        priority queue,       correlator: repeated
      every change gets      3 workers, batches    intrusion, camera
      a sequence number      of up to 8            corroboration
              |                    |                    |
              |                    v                    | raises an incident
              |              triage/llm.py              | back through
              |              OpenAI, JSON schema        | pipeline.submit_event()
              |                    |                    |
              |                    +--------------------+
              |
       +------+------------------+
       v                         v
   hub.py  (GET /ws)       persistence.py
   snapshot, then          write-behind SQLite,
   seq-numbered deltas     coalesced every 250 ms
       |                         |
       v                         v
   React dashboard          data/sentinel.db
   useAlarmFeed.ts          + the resume point
```

Three ideas hold it together:

- **One door in.** Every event, whether it came from the feed, the camera or the escalation correlator, enters through `Pipeline.submit`. Validation, dedupe and rule severity happen once, in one place.
- **The alarm is never blocked by the AI.** The store is written first with a rule-based severity, so the operator sees the alarm immediately. The LLM enriches it a second or so later. A slow or broken model delays a summary, never an alarm.
- **The dashboard is a replica, not a poller.** A client gets one snapshot and then a stream of numbered deltas. If it ever sees a gap in the numbers, it asks for a fresh snapshot.

## Run it

Requires Python 3.11+ and Node 20+.

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
```

Build the dashboard once. The backend serves it:

```bash
cd frontend
npm install
npm run build
```

Then three terminals:

```bash
# 1. the event feed
python simulator/stream.py
```

```bash
# 2. the backend, which also serves the dashboard at http://localhost:8000
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

```bash
# 3. the tests
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

Open **http://localhost:8000**.

`TRIAGE=rules` in `.env` is the default and costs nothing. Set `TRIAGE=openai` and add `OPENAI_API_KEY` to turn the AI layer on.

For UI work with hot reload, run `npm run dev` instead and open http://localhost:5173; it proxies `/api` and `/ws` to the backend.

### Driving the demo

| Action | How |
|---|---|
| Fire a burst of 200 events | press **Enter** in the simulator terminal |
| Play a scripted break-in (triggers an escalated incident) | type **b** then Enter in the simulator terminal |
| Break the AI on purpose | `POST /api/chaos/{off\|slow\|429\|junk\|flaky}` |
| Switch camera feed | the dropdown on the camera panel |

Useful simulator flags: `--junk 0.05` (5% malformed messages), `--burst-every 45`, `--burst-size 200`, `--seed 42`, `--scenario-site`, `--scenario-zone`.

The simulator is the reference generator from the brief, extended with bursts, malformed input and replay so the degradation paths can actually be exercised.

### The endpoints

- `GET /api/health`: stream status and ingest counters
- `GET /api/alarms?limit=20`: newest alarms first
- `POST /api/alarms/{id}/acknowledge`, `POST /api/alarms/{id}/resolve`
- `GET /api/camera/frame`, `GET /api/camera/feeds`, `POST /api/camera/feeds/{id}`
- `POST /api/chaos/{mode}`
- `WS /ws`: the dashboard feed

## Ingest under stress

- **Bursts.** The consumer never awaits slow work. Parse, normalize and store are synchronous and cheap; triage and escalation are handed to background queues. A 200-event burst lands in the store in one pass.
- **Bad input.** Malformed JSON and non-objects are rejected and counted. Everything else is repaired rather than dropped: a missing zone, an out-of-range confidence, an unknown type. What was repaired is recorded on the alarm and shown to the operator, so a degraded event is never silently trusted.
- **Duplicates.** Dedupe by `event_id` over a 100k window, which is also what makes the replay on reconnect safe.
- **Disconnects.** Reconnect with jittered backoff capped at 5 s.
- **Accounting.** `received = accepted + rejected + duplicates`, visible on `/api/health` and in the dashboard status bar. The numbers add up, so nothing can vanish unnoticed.
- **Memory.** The store is bounded: resolved alarms are evicted past 5,000, and the dashboard prunes its own resolved list past 500. A monitoring console that runs for a week should not grow without limit.
- **Slow dashboards.** Each connected client has a bounded queue. A client that cannot keep up is sent a resync snapshot instead of being allowed to back up the server.

## AI triage

Every alarm appears the instant it arrives, with a severity from simple rules. The LLM works in the background and enriches it with a severity, a verdict (likely real, uncertain, probable false alarm), a one-line summary and a recommended action.

- **Model:** `gpt-5.4-mini` with structured JSON output, chosen after sending the same three alarms to five models twice:

  | Model | Latency | Result |
  |---|---|---|
  | gpt-5.4-mini | 1.7 s, 1.7 s | Consistent, specific summaries |
  | gpt-4.1-mini | 2.4 s, 5.6 s | Good, but latency varied |
  | gpt-4o-mini | 2.3 s, 3.1 s | Called low-confidence smoke a false alarm and an animal "likely real" |
  | gpt-4.1-nano, gpt-5.4-nano | 1.7 to 2.9 s | Verdicts changed between identical runs |

  In a live run: 13 of 13 alarms triaged, p50 1.0 s, p95 1.8 s.
- **Safety floor:** panic, fire and smoke stay critical whatever the model says. The model can still mark them uncertain, and the row shows both.
- **Priority and batching:** critical alarms are sent first; under a burst, up to 8 alarms share one call.
- **Degradation:** timeouts (10 s), rate limits, invalid output (validated against a schema, retried once), a spend cap and a deep backlog all fall back to the rule severity, and the row says why. Three failures in a row, or any rate limit, pause AI calls for 30 s. An alarm that has waited more than 60 s is released with its rule severity rather than held.
- **Cost:** tokens are metered per call and priced from `.env`. `LLM_BUDGET_USD` is a hard cap per run. In testing, a quiet stream cost about $0.0006 per alarm.
- **Untrusted input:** alarm fields are sent as JSON data, and the prompt tells the model never to follow instructions inside them. The output can only set enumerated fields.
- **Swappable:** the model sits behind a small `Triager` interface. Another provider or a local model is one class.
- **Failure injection:** `POST /api/chaos/{off|slow|429|junk|flaky}` makes the AI misbehave on purpose, to show degradation live.
- **Measured, not claimed:** the status bar shows AI call p50 and p95, end-to-end alarm-to-summary p95, and spend so far.

## Alerting and escalation

- **Impossible to miss:** while any critical alarm is unacknowledged, a red banner stays pinned to the top with the count, the number of escalated incidents and the age of the oldest. The browser tab title becomes `(3) CRITICAL · Sentinel`, so it is visible from another tab. A tone plays when a new critical arrives, at most one every 2 s so a burst does not become noise.
- **Escalation on patterns:** a correlator watches every accepted alarm and raises one critical incident when:
  - **Repeated intrusion:** 3 confident intrusion alarms (breach, forced door, glass break) at one site within 2 minutes.
  - **Corroborated by camera:** the camera sees a person and an intrusion sensor fires in the same zone within 2 minutes.
- **One incident, not a stream:** while an incident is open, related alarms join it. Linked alarms are tagged, and acknowledging or resolving the incident applies to all of them. Alarms already grouped cannot open a second incident.
- **Tuning evidence:** on the reference stream (about one alarm per second across 7 sites, types chosen uniformly at random), an hour of 3,356 alarms produced 18 incidents grouping 384 alarms. An earlier version of the rule produced over 100 an hour, which would have been worse than no escalation at all. A real site is far quieter, so the thresholds are configurable (`ESCALATION_WINDOW_S`, `ESCALATION_THRESHOLD`).
- **Incidents go through the same pipeline** (`Pipeline.submit_event`), so they are stored, pushed to dashboards and summarised by the AI like any alarm. They can never be downgraded below critical. The feed cannot forge one: an external event claiming `source: system` is flagged and treated as a sensor.

## Camera

A camera worker turns video into alarms that flow through the same pipeline, triage and dashboard as sensor events.

- **Off the hot path:** decoding and detection run in a separate process, so they never compete with the event loop that ingests the stream. The backend moves its detections into `Pipeline.submit` like any other event. If the worker dies, it is restarted.
- **Never behind real time:** a reader thread keeps only the newest frame. The detector samples it at `CAMERA_FPS` (4 by default); older frames are skipped, not queued.
- **Detector:** YOLO26 nano exported to ONNX at 416 px, run with ONNX Runtime on CPU, plus our own NMS. On a laptop Ryzen 5 with no GPU: 22 ms p50, 35 ms p95 per frame. It reports people, vehicles and animals.
- **No alarm spam:** a small IoU tracker gives each object one identity. An object raises one alarm once it is seen in two frames, a person who stays past `CAMERA_LOITER_S` raises one loitering alarm, and an object that flickers out and back at the same spot within 30 s is suppressed.
- **Evidence:** every camera alarm carries a snapshot with the object boxed, shown as a thumbnail on the dashboard. The dashboard also shows the live annotated feed and the worker's numbers.
- **Feeds:** `feeds.json` lists the camera feeds by name and zone; feeds whose file is missing are skipped. The dashboard has a feed switcher: switching restarts the worker on the new source in about 3 seconds, and alarms carry the new zone. An enlarge button opens the live annotated view full size.
- **Feeds shipped:** five looped clips in `footage/`: a street corner at night (Pexels), a driveway at night with a person approaching a car, a warehouse floor, a four-camera stairwell and garage view, and a construction site perimeter. `CAMERA_SOURCE` adds an extra source, such as an RTSP or HLS URL or a webcam index. To simulate a real IP camera, publish a clip with MediaMTX and point `CAMERA_SOURCE` at it:

  ```bash
  ffmpeg -re -stream_loop -1 -i footage/cctv.mp4 -c copy -f rtsp rtsp://localhost:8554/cam1
  ```

  The model file is Ultralytics YOLO26n, licensed AGPL-3.0.

## Never lose an alarm

- **Saved as it happens:** every alarm change is written to SQLite (`data/sentinel.db`) by a write-behind task: changes are collected and saved in one transaction every 250 ms, in a worker thread, so disk latency never blocks the stream. Several changes to one alarm between saves are written once.
- **Restored on start:** open alarms, their triage and their status come back after a restart. Alarms still waiting for the AI are queued again.
- **Replay of what was missed:** the backend saves the id of the last stream event it processed, in the same transaction. On reconnect it asks the feed for `?since=<id>`, and the simulator replays everything after it from a 5,000-message history. Dedupe by event id means a replayed alarm is never stored twice. A feed without replay simply ignores the parameter.
- **Tested with a crash:** the backend was killed hard mid-stream, the simulator kept sending for 10 s, and the backend was restarted. An independent client recorded every event the simulator sent: all 27 events from the backend's first connection onward were stored, including the 11 sent while it was down.

## Trade-offs and cut corners

Written down because they are real, not because they went unnoticed.

- **In-memory is the truth, SQLite is a mirror.** The store is the source of truth and the database trails it by up to 250 ms. A crash in that window loses the *status* changes of that moment, though the stream replay brings the events themselves back. Making the database authoritative would have meant a write on the hot path, which is the wrong trade for a console whose job is to never stall.
- **One process, no horizontal scale.** One store, one hub, one correlator. Running two backends would need shared state (Redis or Postgres) and a shared bus. Fine for one site, wrong for a hundred.
- **No auth.** Anyone who can reach port 8000 can acknowledge and resolve alarms. A real deployment needs operator accounts, per-site permissions and an audit trail of who acknowledged what.
- **The escalation window is not persisted.** A pattern that spans a restart starts counting again.
- **Batched triage has a blast radius.** Up to 8 alarms share a call, which cuts cost and latency under a burst, but one malformed response retries all 8.
- **Replay has limits.** Events sent before the backend ever connected for the first time are not backfilled, and the simulator's buffer covers about 80 minutes of downtime at its rate.
- **Vision is generic.** Detection is COCO classes at 416 px on CPU. No zone or tripwire geometry, no re-identification of the same person across cameras, no frame captioning. A loitering alarm is a timer on a tracked box, not scene understanding.
- **Rule severity is a hand-written table.** It is deliberately blunt: its job is to be a safe floor under the model, not to be clever.
- **Backend tests only.** 98 tests cover ingest, normalization, the store, rules, the triage service and its fallbacks, escalation, the hub, persistence and the API. The frontend was verified by hand and by driving a real browser, not by an automated suite. That is the gap I would close first.
- **The simulator is not a real feed.** It is the reference generator plus bursts, junk and replay. A production feed would not offer `?since=`, so the replay guarantee would have to move to a broker.

## What I would build next

1. **A frontend test suite**, and a golden-set eval harness for triage so a model change can be scored instead of eyeballed.
2. **Operator feedback:** a "this was a false alarm" button that feeds back as examples, so triage improves on a site's own history.
3. **Auth and audit:** operator accounts, per-site permissions, and a record of who acknowledged what and when.
4. **Shared state:** Postgres and Redis so several backends and many dashboards can run behind a load balancer.
5. **Richer vision:** zone and tripwire rules, and a frame caption passed to the LLM so the summary describes the scene, not just the label.
6. **Fan-out:** SMS, push and phone for criticals, with on-call rotation and acknowledge-or-escalate timers.
7. **Per-site history and a shift handover report**, so an operator coming on shift sees what happened on the last one.

## Tests

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

98 tests, about 3 seconds, no network and no API key required (`conftest.py` pins `TRIAGE=rules`, a temporary database and the camera off).
