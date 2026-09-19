# Project Sentinel

A miniature real-time alarm monitoring service: it ingests a live stream of sensor and camera events, triages each one with an LLM, and shows them to an operator on a live dashboard.

> Work in progress. Architecture, trade-offs and the demo link will be added as the pieces land.

## Scope

The five core requirements come first and must work end to end. On top of that I chose two stretch goals:

- **Correlation and escalation:** repeated or combined signals at one site become a single escalated incident. It completes the "escalate on patterns" part of the alerting rule, and it cuts the noise an operator has to read.
- **Operability (AI cost and latency metrics):** the dashboard shows what the AI layer costs and how fast it answers, so its trade-offs are visible and measured.

Deliberately not built: deeper vision (zone and tripwire rules, frame captioning), persistence and per-site history, the operator feedback loop, and dashboard auth. They are listed under "What I would build next".

## AI triage

Every alarm is shown the moment it arrives, with a severity from simple rules. The LLM works in the background and enriches it a second or so later with a severity, a verdict (likely real, uncertain, probable false alarm), a one-line summary and a recommended action. A slow or failing model can delay the summary, never the alarm.

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
- **Degradation:** timeouts (10 s), rate limits, invalid output (validated against a schema, retried once), a spend cap and a deep backlog all fall back to the rule severity, and the row says why. Three failures in a row, or any rate limit, pause AI calls for 30 s.
- **Cost:** tokens are metered per call and priced from `.env`. `LLM_BUDGET_USD` is a hard cap per run. In testing, a quiet stream cost about $0.0006 per alarm.
- **Untrusted input:** alarm fields are sent as JSON data, and the prompt tells the model never to follow instructions inside them. The output can only set enumerated fields.
- **Swappable:** the model sits behind a small `Triager` interface. Another provider or a local model is one class.
- **Failure injection:** `POST /api/chaos/{off|slow|429|junk|flaky}` makes the AI misbehave on purpose, to show degradation live.

## Alerting and escalation

- **Impossible to miss:** while any critical alarm is unacknowledged, a red banner stays pinned to the top with the count, the number of escalated incidents and the age of the oldest. The browser tab title becomes `(3) CRITICAL · Sentinel`, so it is visible from another tab. An optional tone plays when a new critical arrives (at most one every 2 s, so a burst does not become noise).
- **Escalation on patterns:** a correlator watches every accepted alarm and raises one critical incident when:
  - **Repeated intrusion:** 3 confident intrusion alarms (breach, forced door, glass break) at one site within 2 minutes.
  - **Corroborated by camera:** the camera sees a person and an intrusion sensor fires in the same zone within 2 minutes.
- **One incident, not a stream:** while an incident is open, related alarms join it. Linked alarms are tagged, and acknowledging or resolving the incident applies to all of them. Alarms already grouped cannot open a second incident.
- **Tuning evidence:** on the reference stream (about one alarm per second across 7 sites, types chosen uniformly at random), an hour of 3,356 alarms produced 18 incidents grouping 384 alarms. A real site is far quieter, so the thresholds are configurable (`ESCALATION_WINDOW_S`, `ESCALATION_THRESHOLD`).
- **Demo trigger:** type `b` and Enter in the simulator terminal to play a scripted break-in (forced door, perimeter breach, glass break) at `--scenario-site` / `--scenario-zone`.
- **Incidents go through the same pipeline** (`Pipeline.submit_event`), so they are stored, pushed to dashboards and summarised by the AI like any alarm. They can never be downgraded below critical. The feed cannot forge one: an external event claiming `source: system` is flagged and treated as a sensor.

## Camera

A camera worker turns video into alarms that flow through the same pipeline, triage and dashboard as sensor events.

- **Off the hot path:** decoding and detection run in a separate process, so they never compete with the event loop that ingests the stream. The backend moves its detections into `Pipeline.submit` like any other event. If the worker dies, it is restarted.
- **Never behind real time:** a reader thread keeps only the newest frame. The detector samples it at `CAMERA_FPS` (4 by default); older frames are skipped, not queued.
- **Detector:** YOLO26 nano exported to ONNX at 416 px, run with ONNX Runtime on CPU, plus our own NMS. On a laptop Ryzen 5 with no GPU: 22 ms p50, 35 ms p95 per frame. It reports people, vehicles and animals.
- **No alarm spam:** a small IoU tracker gives each object one identity. An object raises one alarm once it is seen in two frames, a person who stays past `CAMERA_LOITER_S` raises one loitering alarm, and an object that flickers out and back at the same spot within 30 s is suppressed.
- **Evidence:** every camera alarm carries a snapshot with the object boxed, shown as a thumbnail on the dashboard. The dashboard also shows the live annotated feed and the worker's numbers.
- **Feeds:** `feeds.json` lists the camera feeds by name and zone. Feeds whose file is missing are skipped. The dashboard has a feed switcher: switching restarts the worker on the new source in about 3 seconds, and alarms carry the new zone. An **Enlarge** button opens the live annotated view full size.
- **Feed used:** `footage/cctv.mp4` (a free Pexels clip, looped) ships with the repo. `CAMERA_SOURCE` adds an extra source, such as an RTSP or HLS URL or a webcam index. To simulate a real IP camera, publish the clip with MediaMTX and point `CAMERA_SOURCE` at it:

  ```bash
  ffmpeg -re -stream_loop -1 -i footage/cctv.mp4 -c copy -f rtsp rtsp://localhost:8554/cam1
  ```

  The model file is Ultralytics YOLO26n, licensed AGPL-3.0.

## Run it (so far)

Requires Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
```

Start the event simulator:

```bash
python simulator/stream.py
```

It emits a bursty stream on `ws://localhost:8765`. Useful flags:

| Flag | What it does |
|---|---|
| `--junk 0.05` | 5% of messages are malformed (missing fields, bad confidence, unknown type, broken JSON, duplicates) |
| `--burst-every 45` | fire a burst of events every 45 seconds |
| `--burst-size 200` | events per burst (default 200) |
| `--seed 42` | repeatable run |

Press **Enter** in the simulator terminal to fire a burst on demand.

The simulator is the reference generator from the brief, extended with bursts and malformed input so the pipeline's degradation paths can be exercised.

Start the backend in a second terminal:

```bash
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Build the operator dashboard once (requires Node 20+). The backend serves it at http://localhost:8000:

```bash
cd frontend
npm install
npm run build
```

For UI work with hot reload, run `npm run dev` instead and open http://localhost:5173 (it proxies `/api` and `/ws` to the backend).

- `GET http://localhost:8000/api/health`: stream status and ingest counters
- `GET http://localhost:8000/api/alarms?limit=20`: newest alarms first

Run the tests:

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```
