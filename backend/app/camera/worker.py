import logging
import os
import queue
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .detector import YoloOnnx
from .tracking import EventPolicy, Track, Tracker

log = logging.getLogger("sentinel.camera")

STATS_EVERY_S = 2.0
MAX_SNAPSHOTS = 500
BOX_COLOURS = {"person": (60, 80, 240), "vehicle": (40, 170, 240), "animal": (170, 170, 170)}


class LatestFrameReader(threading.Thread):
    """Reads the source as fast as it produces frames and keeps only the newest one.

    The detector always gets the most recent frame, so a slow detection never
    builds a backlog of stale video. Files loop; streams reconnect with backoff.
    """

    def __init__(self, source: str, stop: threading.Event) -> None:
        super().__init__(daemon=True, name="frame-reader")
        self.source = int(source) if source.isdigit() else source
        self.is_file = isinstance(self.source, str) and os.path.isfile(self.source)
        self.stop_event = stop
        self.status = "starting"
        self.source_fps = 0.0
        self.frames_read = 0
        self.frames_skipped = 0
        self.reconnects = 0
        self._lock = threading.Lock()
        self._frame = None
        self._fresh = False

    def take(self):
        with self._lock:
            if not self._fresh:
                return None
            self._fresh = False
            return self._frame

    def run(self) -> None:
        backoff = 1.0
        while not self.stop_event.is_set():
            capture = cv2.VideoCapture(self.source)
            if not capture.isOpened():
                self._wait_to_reconnect(backoff, "cannot open source")
                backoff = min(backoff * 2, 10)
                continue
            backoff = 1.0
            self.status = "streaming"
            fps = capture.get(cv2.CAP_PROP_FPS)
            self.source_fps = fps if 0 < fps <= 120 else 25.0
            self._read_until_end(capture)
            capture.release()
            if self.is_file:
                continue
            self._wait_to_reconnect(backoff, "stream ended")
            backoff = min(backoff * 2, 10)

    def _read_until_end(self, capture) -> None:
        frame_time = 1.0 / self.source_fps
        next_frame = time.monotonic()
        while not self.stop_event.is_set():
            ok, frame = capture.read()
            if not ok:
                return
            with self._lock:
                if self._fresh:
                    self.frames_skipped += 1
                self._frame, self._fresh = frame, True
            self.frames_read += 1
            if self.is_file:
                next_frame += frame_time
                delay = next_frame - time.monotonic()
                if delay > 0:
                    self.stop_event.wait(delay)
                else:
                    next_frame = time.monotonic()

    def _wait_to_reconnect(self, seconds: float, reason: str) -> None:
        self.status = "reconnecting"
        self.reconnects += 1
        log.warning("camera %s, retrying in %.0fs", reason, seconds)
        self.stop_event.wait(seconds)


def run(config: dict, events, frames, stop) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    snapshot_dir = Path(config["snapshot_dir"])
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    detector = YoloOnnx(config["model"], confidence=config["confidence"])
    reader = LatestFrameReader(config["source"], stop)
    reader.start()
    tracker = Tracker()
    policy = EventPolicy(loiter_s=config["loiter_s"])
    snapshots: deque[Path] = deque()
    inference_ms: deque[float] = deque(maxlen=100)
    processed = sent = dropped = 0
    interval = 1.0 / config["fps"]
    next_tick = time.monotonic()
    next_stats = next_tick
    log.info("camera %s watching %s at %.1f fps", config["camera_id"], config["source"], config["fps"])

    while not stop.is_set():
        frame = reader.take()
        if frame is not None:
            started = time.monotonic()
            detections = detector.detect(frame)
            inference_ms.append((time.monotonic() - started) * 1000)
            processed += 1
            now = time.monotonic()
            tracks = tracker.update(detections, now)
            for event_type, track in policy.events_for(tracks, now):
                event = build_event(event_type, track, now, config)
                save_snapshot(frame, track, snapshot_dir / f"{event['event_id']}.jpg", snapshots)
                if offer(events, {"kind": "event", "event": event}):
                    sent += 1
                else:
                    dropped += 1
            offer_latest(frames, encode(annotate(frame, tracks), width=960, quality=70))

        now = time.monotonic()
        if now >= next_stats:
            next_stats = now + STATS_EVERY_S
            ordered = sorted(inference_ms)
            offer(events, {"kind": "stats", "stats": {
                "camera_id": config["camera_id"],
                "site_id": config["site_id"],
                "zone": config["zone"],
                "source": os.path.basename(str(config["source"])),
                "status": reader.status,
                "source_fps": round(reader.source_fps, 1),
                "target_fps": config["fps"],
                "frames_read": reader.frames_read,
                "frames_processed": processed,
                "frames_skipped": reader.frames_skipped,
                "reconnects": reader.reconnects,
                "inference_p50_ms": round(ordered[len(ordered) // 2], 1) if ordered else None,
                "inference_p95_ms": round(ordered[int(len(ordered) * 0.95)], 1) if ordered else None,
                "active_tracks": len(tracker.tracks),
                "events_sent": sent,
                "events_suppressed": policy.suppressed,
                "events_dropped": dropped,
            }})

        next_tick += interval
        wait = next_tick - time.monotonic()
        if wait > 0:
            stop.wait(wait)
        else:
            next_tick = time.monotonic()

    reader.join(timeout=2)


def build_event(event_type: str, track: Track, now: float, config: dict) -> dict:
    event_id = "cam_" + uuid.uuid4().hex[:10]
    metadata = {
        "object": track.kind,
        "class": track.label,
        "bbox": list(track.box),
        "track_id": track.track_id,
        "camera_id": config["camera_id"],
    }
    if event_type == "loitering":
        metadata["dwell_s"] = round(now - track.first_seen, 1)
    return {
        "event_id": event_id,
        "site_id": config["site_id"],
        "zone": config["zone"],
        "type": event_type,
        "source": "camera",
        "confidence": round(track.confidence, 2),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot_url": f"/snapshots/{event_id}.jpg",
        "metadata": metadata,
    }


def annotate(frame: np.ndarray, tracks: list[Track], highlight: Track | None = None) -> np.ndarray:
    image = frame.copy()
    for track in tracks:
        x, y, w, h = track.box
        colour = BOX_COLOURS[track.kind]
        thickness = 4 if track is highlight else 2
        cv2.rectangle(image, (x, y), (x + w, y + h), colour, thickness)
        cv2.putText(image, f"{track.label} #{track.track_id} {track.confidence:.0%}", (x, max(18, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2, cv2.LINE_AA)
    return image


def encode(image: np.ndarray, width: int, quality: int) -> bytes:
    height = round(image.shape[0] * width / image.shape[1])
    resized = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buffer.tobytes() if ok else b""


def save_snapshot(frame: np.ndarray, track: Track, path: Path, snapshots: deque) -> None:
    path.write_bytes(encode(annotate(frame, [track], highlight=track), width=960, quality=80))
    snapshots.append(path)
    while len(snapshots) > MAX_SNAPSHOTS:
        snapshots.popleft().unlink(missing_ok=True)


def offer(q, item) -> bool:
    try:
        q.put_nowait(item)
        return True
    except queue.Full:
        return False


def offer_latest(q, item) -> None:
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        offer(q, item)
