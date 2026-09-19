import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .config import ROOT, settings
from .hub import RESYNC, DashboardHub
from .pipeline import Pipeline
from .store import AlarmNotFound, AlarmStore, InvalidTransition
from .stream_client import StreamClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sentinel")

store = AlarmStore()
pipeline = Pipeline(store)
hub = DashboardHub(store)
stream = StreamClient(settings.stream_url, pipeline)


def current_stats() -> dict:
    return {
        "stream_connected": stream.connected,
        "stream_retries": stream.retries,
        **asdict(pipeline.stats),
        "stored": len(store),
        "dashboards": hub.client_count,
        "resyncs": hub.resyncs,
    }


async def publish_stats(every_seconds: float = 1) -> None:
    while True:
        await asyncio.sleep(every_seconds)
        hub.publish_stats(current_stats())


async def log_stats(every_seconds: float = 10) -> None:
    while True:
        await asyncio.sleep(every_seconds)
        s = pipeline.stats
        log.info(
            "ingest: received=%d accepted=%d repaired=%d rejected=%d duplicates=%d | stored=%d | stream=%s | dashboards=%d",
            s.received, s.accepted, s.repaired, s.rejected, s.duplicates,
            len(store), "up" if stream.connected else "down", hub.client_count,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [
        asyncio.create_task(stream.run(), name="stream"),
        asyncio.create_task(publish_stats(), name="publish-stats"),
        asyncio.create_task(log_stats(), name="log-stats"),
    ]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Project Sentinel", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return current_stats()


@app.get("/api/alarms")
async def list_alarms(limit: int = 100):
    return store.recent(limit)


@app.post("/api/alarms/{event_id}/acknowledge")
async def acknowledge(event_id: str):
    return _change_status(store.acknowledge, event_id)


@app.post("/api/alarms/{event_id}/resolve")
async def resolve(event_id: str):
    return _change_status(store.resolve, event_id)


def _change_status(action, event_id: str):
    try:
        return action(event_id)
    except AlarmNotFound:
        raise HTTPException(status_code=404, detail="alarm not found")
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.websocket("/ws")
async def dashboard_socket(ws: WebSocket):
    await ws.accept()
    queue, snapshot = hub.connect()
    try:
        await ws.send_text(snapshot)
        while True:
            message = await queue.get()
            if message is RESYNC:
                message = hub.snapshot_message()
            await ws.send_text(message)
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(queue)


dist = ROOT / "frontend" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
