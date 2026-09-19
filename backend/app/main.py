import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .camera.bridge import CameraBridge, UnknownFeed
from .config import ROOT, SNAPSHOT_DIR, camera_config, initial_feed, load_feeds, settings
from .escalation import Correlator
from .hub import RESYNC, DashboardHub
from .pipeline import Pipeline
from .store import AlarmNotFound, AlarmStore, InvalidTransition
from .stream_client import StreamClient
from .triage.llm import ChaosTriager, OpenAITriager
from .triage.service import TriageService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("sentinel")


def build_triager():
    if settings.triage != "openai":
        return None
    if not settings.openai_api_key:
        log.warning("TRIAGE=openai but OPENAI_API_KEY is empty, using rules only")
        return None
    openai_triager = OpenAITriager(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        reasoning_effort=settings.openai_reasoning_effort,
        timeout_s=settings.llm_timeout_s,
        site_timezone=settings.site_timezone,
    )
    return ChaosTriager(openai_triager, settings.llm_chaos)


store = AlarmStore()
hub = DashboardHub(store)
triage = TriageService(
    store,
    build_triager(),
    budget_usd=settings.llm_budget_usd,
    price_input_per_1m=settings.price_input_per_1m,
    price_output_per_1m=settings.price_output_per_1m,
    timeout_s=settings.llm_timeout_s,
)
pipeline = Pipeline(store)
correlator = Correlator(
    pipeline, store, window_s=settings.escalation_window_s, repeat_threshold=settings.escalation_threshold
)
pipeline.add_listener(triage.submit)
pipeline.add_listener(correlator.observe)
stream = StreamClient(settings.stream_url, pipeline)
feeds = load_feeds()
start_feed = initial_feed(feeds)
camera = CameraBridge(feeds, start_feed, camera_config, pipeline) if start_feed else None


def current_stats() -> dict:
    return {
        "stream_connected": stream.connected,
        "stream_retries": stream.retries,
        **asdict(pipeline.stats),
        "stored": len(store),
        "dashboards": hub.client_count,
        "resyncs": hub.resyncs,
        "ai": triage.stats(),
        "escalation": correlator.stats(),
        "camera": camera.stats() if camera else None,
    }


async def publish_stats(every_seconds: float = 1) -> None:
    while True:
        await asyncio.sleep(every_seconds)
        hub.publish_stats(current_stats())


async def log_stats(every_seconds: float = 10) -> None:
    while True:
        await asyncio.sleep(every_seconds)
        s, ai = pipeline.stats, triage.stats()
        log.info(
            "ingest: received=%d accepted=%d repaired=%d rejected=%d duplicates=%d | stored=%d | stream=%s"
            " | ai=%s triaged=%d fallbacks=%d queue=%d spent=$%.4f",
            s.received, s.accepted, s.repaired, s.rejected, s.duplicates,
            len(store), "up" if stream.connected else "down",
            ai["state"], ai["ai_triaged"], ai["fallbacks"], ai["queue_depth"], ai["spent_usd"],
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("triage mode: %s", triage.stats()["model"] or "rules only")
    tasks = [
        asyncio.create_task(stream.run(), name="stream"),
        asyncio.create_task(triage.run(), name="triage"),
        asyncio.create_task(publish_stats(), name="publish-stats"),
        asyncio.create_task(log_stats(), name="log-stats"),
    ]
    if camera:
        camera.start()
        tasks.append(asyncio.create_task(camera.pump(), name="camera"))
    yield
    if camera:
        camera.stop()
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


@app.post("/api/chaos/{mode}")
async def set_chaos(mode: str):
    if not isinstance(triage.triager, ChaosTriager):
        raise HTTPException(status_code=409, detail="AI triage is off")
    if mode not in ChaosTriager.MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of: {', '.join(ChaosTriager.MODES)}")
    triage.triager.mode = mode
    log.warning("chaos mode set to %s", mode)
    return {"chaos": mode}


@app.get("/api/camera/frame")
async def camera_frame():
    if not camera or not camera.latest_frame:
        return Response(status_code=204)
    return Response(camera.latest_frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/camera/feeds")
async def camera_feeds():
    if not camera:
        return {"active": None, "feeds": []}
    return camera.feed_list()


@app.post("/api/camera/feeds/{feed_id}")
async def switch_camera_feed(feed_id: str):
    if not camera:
        raise HTTPException(status_code=409, detail="camera is off")
    try:
        return await camera.switch(feed_id)
    except UnknownFeed:
        raise HTTPException(status_code=404, detail="unknown feed")


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


SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/snapshots", StaticFiles(directory=SNAPSHOT_DIR), name="snapshots")

dist = ROOT / "frontend" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
