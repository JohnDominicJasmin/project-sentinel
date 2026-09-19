import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI

from .config import settings
from .pipeline import Pipeline
from .store import AlarmStore
from .stream_client import StreamClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sentinel")

store = AlarmStore()
pipeline = Pipeline(store)
stream = StreamClient(settings.stream_url, pipeline)


async def report_stats(every_seconds: float = 10) -> None:
    while True:
        await asyncio.sleep(every_seconds)
        s = pipeline.stats
        log.info(
            "ingest: received=%d accepted=%d repaired=%d rejected=%d duplicates=%d | stored=%d | stream=%s",
            s.received, s.accepted, s.repaired, s.rejected, s.duplicates,
            len(store), "up" if stream.connected else "down",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [
        asyncio.create_task(stream.run(), name="stream"),
        asyncio.create_task(report_stats(), name="stats"),
    ]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Project Sentinel", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {
        "stream": {"url": stream.url, "connected": stream.connected, "retries": stream.retries},
        "ingest": asdict(pipeline.stats),
        "alarms_stored": len(store),
    }


@app.get("/api/alarms")
async def list_alarms(limit: int = 100):
    return store.list(limit)
