import asyncio
import logging
import multiprocessing as mp
import queue
from typing import Callable, Optional

from ..pipeline import Pipeline
from . import worker

log = logging.getLogger("sentinel.camera")

RESTART_DELAY_S = 3.0


class UnknownFeed(KeyError):
    pass


class CameraBridge:

    def __init__(self, feeds: list[dict], feed: dict, make_config: Callable[[dict], dict], pipeline: Pipeline) -> None:
        self.feeds = feeds
        self.feed = feed
        self.make_config = make_config
        self.pipeline = pipeline
        self.ctx = mp.get_context("spawn")
        self.events = self.ctx.Queue(maxsize=500)
        self.frames = self.ctx.Queue(maxsize=1)
        self.stop_event = self.ctx.Event()
        self.process: Optional[mp.Process] = None
        self.latest_frame: Optional[bytes] = None
        self.worker_stats: dict = {"status": "starting"}
        self.events_received = 0
        self.restarts = 0
        self._switching = asyncio.Lock()

    def stats(self) -> dict:
        return {
            **self.worker_stats,
            "feed_id": self.feed["id"],
            "feed_name": self.feed["name"],
            "events_received": self.events_received,
            "worker_restarts": self.restarts,
        }

    def feed_list(self) -> dict:
        return {
            "active": self.feed["id"],
            "feeds": [{"id": f["id"], "name": f["name"], "zone": f["zone"]} for f in self.feeds],
        }

    def start(self) -> None:
        self.stop_event = self.ctx.Event()
        self.process = self.ctx.Process(
            target=worker.run,
            args=(self.make_config(self.feed), self.events, self.frames, self.stop_event),
            name="camera-worker",
            daemon=True,
        )
        self.process.start()
        log.info("camera worker started on %s (pid %s)", self.feed["name"], self.process.pid)

    async def switch(self, feed_id: str) -> dict:
        feed = next((f for f in self.feeds if f["id"] == feed_id), None)
        if feed is None:
            raise UnknownFeed(feed_id)
        async with self._switching:
            if feed["id"] != self.feed["id"]:
                await asyncio.to_thread(self.stop)
                self.feed = feed
                self.latest_frame = None
                self.worker_stats = {"status": "switching"}
                self.start()
        return self.feed_list()

    async def pump(self) -> None:
        while True:
            self._drain_events()
            self._take_latest_frame()
            if self._crashed():
                self.worker_stats = {**self.worker_stats, "status": "restarting"}
                log.error("camera worker exited with code %s, restarting", self.process.exitcode)
                await asyncio.sleep(RESTART_DELAY_S)
                if self._crashed():
                    self.restarts += 1
                    self.start()
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self.stop_event.set()
        if self.process and self.process.is_alive():
            self.process.join(timeout=3)
            if self.process.is_alive():
                self.process.terminate()

    def _crashed(self) -> bool:
        return bool(self.process) and not self.process.is_alive() and not self.stop_event.is_set()

    def _drain_events(self, limit: int = 200) -> None:
        for _ in range(limit):
            try:
                message = self.events.get_nowait()
            except queue.Empty:
                return
            if message["kind"] == "event":
                self.events_received += 1
                self.pipeline.submit(message["event"], origin="camera")
            elif message["kind"] == "stats" and message["stats"].get("zone") == self.feed["zone"]:
                self.worker_stats = message["stats"]

    def _take_latest_frame(self) -> None:
        while True:
            try:
                self.latest_frame = self.frames.get_nowait()
            except queue.Empty:
                return
