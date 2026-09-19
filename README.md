# Project Sentinel

A miniature real-time alarm monitoring service: it ingests a live stream of sensor and camera events, triages each one with an LLM, and shows them to an operator on a live dashboard.

> Work in progress. Architecture, trade-offs and the demo link will be added as the pieces land.

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
