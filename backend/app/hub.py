import asyncio
import json

from .models import Alarm
from .store import AlarmStore

RESYNC = object()


class DashboardHub:

    def __init__(self, store: AlarmStore, queue_size: int = 2000) -> None:
        self.store = store
        self.queue_size = queue_size
        self._queues: set[asyncio.Queue] = set()
        self.resyncs = 0
        store.subscribe(self._on_change)

    @property
    def client_count(self) -> int:
        return len(self._queues)

    def connect(self) -> tuple[asyncio.Queue, str]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self._queues.add(queue)
        return queue, self.snapshot_message()

    def disconnect(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)

    def snapshot_message(self) -> str:
        alarms = [a.model_dump(mode="json") for a in self.store.snapshot()]
        return json.dumps({"type": "snapshot", "seq": self.store.seq, "alarms": alarms})

    def publish_stats(self, stats: dict) -> None:
        self._broadcast(json.dumps({"type": "stats", "stats": stats}))

    def _on_change(self, alarm: Alarm) -> None:
        self._broadcast(json.dumps({"type": "alarm", "seq": alarm.seq, "alarm": alarm.model_dump(mode="json")}))

    def _broadcast(self, message: str) -> None:
        for queue in self._queues:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(RESYNC)
                self.resyncs += 1
