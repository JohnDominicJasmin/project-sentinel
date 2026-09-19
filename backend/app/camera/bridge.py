import asyncio
import logging
import multiprocessing as mp
import queue
from typing import Optional

from ..pipeline import Pipeline
from . import worker

log = logging.getLogger("sentinel.camera")

RESTART_DELAY_S = 3.0


class CameraBridge:
    """Owns the camera worker process and moves its detections into the pipeline.

    Decoding and inference run in a separate process, so they never compete
    with the event loop that ingests the alarm stream. If the worker dies, it
    is restarted.
    """

    def __init__(self, config: dict, pipeline: Pipeline) -> None:
        self.config = config
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

    def stats(self) -> dict:
        return {**self.worker_stats, "events_received": self.events_received, "worker_restarts": self.restarts}

    def start(self) -> None:
        self.process = self.ctx.Process(
            target=worker.run,
            args=(self.config, self.events, self.frames, self.stop_event),
            name="camera-worker",
            daemon=True,
        )
        self.process.start()
        log.info("camera worker started (pid %s)", self.process.pid)

    async def pump(self) -> None:
        while True:
            self._drain_events()
            self._take_latest_frame()
            if self.process and not self.process.is_alive() and not self.stop_event.is_set():
                self.worker_stats = {**self.worker_stats, "status": "restarting"}
                log.error("camera worker exited with code %s, restarting", self.process.exitcode)
                await asyncio.sleep(RESTART_DELAY_S)
                self.restarts += 1
                self.start()
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self.stop_event.set()
        if self.process and self.process.is_alive():
            self.process.join(timeout=3)
            if self.process.is_alive():
                self.process.terminate()

    def _drain_events(self, limit: int = 200) -> None:
        for _ in range(limit):
            try:
                message = self.events.get_nowait()
            except queue.Empty:
                return
            if message["kind"] == "event":
                self.events_received += 1
                self.pipeline.submit(message["event"], origin="camera")
            elif message["kind"] == "stats":
                self.worker_stats = message["stats"]

    def _take_latest_frame(self) -> None:
        while True:
            try:
                self.latest_frame = self.frames.get_nowait()
            except queue.Empty:
                return
