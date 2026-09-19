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
