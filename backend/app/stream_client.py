import asyncio
import logging
import random
from typing import Optional
from urllib.parse import quote

import websockets

from .pipeline import Pipeline

log = logging.getLogger("sentinel.stream")

MAX_BACKOFF_SECONDS = 5


class StreamClient:
    def __init__(self, url: str, pipeline: Pipeline) -> None:
        self.url = url
        self.pipeline = pipeline
        self.connected = False
        self.retries = 0
        self.last_event_id: Optional[str] = None

    def connect_url(self) -> str:
        if not self.last_event_id:
            return self.url
        joiner = "&" if "?" in self.url else "?"
        return f"{self.url}{joiner}since={quote(self.last_event_id)}"

    async def run(self) -> None:
        delay = 1.0
        while True:
            try:
                async with websockets.connect(self.connect_url()) as ws:
                    self.connected = True
                    delay = 1.0
                    log.info("connected to %s (resume after %s)", self.url, self.last_event_id or "start")
                    async for message in ws:
                        alarm = self.pipeline.submit(message)
                        if alarm and not alarm.event.event_id.startswith("gen_"):
                            self.last_event_id = alarm.event.event_id
                log.warning("stream closed by server")
            except asyncio.CancelledError:
                raise
            except (OSError, websockets.WebSocketException) as exc:
                log.warning("stream unavailable (%s)", exc.__class__.__name__)
            except Exception:
                log.exception("stream reader error")
            finally:
                self.connected = False

            self.retries += 1
            wait = delay + random.uniform(0, 0.5)
            log.info("reconnecting in %.1fs", wait)
            await asyncio.sleep(wait)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)
