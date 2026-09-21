import itertools
from dataclasses import dataclass

from .detector import OBJECT_KIND, Box, Detection


@dataclass
class Track:
    track_id: int
    label: str
    box: Box
    confidence: float
    first_seen: float
    last_seen: float
    hits: int = 1
    reported: bool = False
    loiter_reported: bool = False

    @property
    def kind(self) -> str:
        return OBJECT_KIND[self.label]


def iou(a: Box, b: Box) -> float:
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    w = max(0, min(ax2, bx2) - max(a[0], b[0]))
    h = max(0, min(ay2, by2) - max(a[1], b[1]))
    overlap = w * h
    union = a[2] * a[3] + b[2] * b[3] - overlap
    return overlap / union if union else 0.0


class Tracker:

    def __init__(self, iou_threshold: float = 0.25, max_missing_s: float = 2.0) -> None:
        self.iou_threshold = iou_threshold
        self.max_missing_s = max_missing_s
        self.tracks: dict[int, Track] = {}
        self._ids = itertools.count(1)

    def update(self, detections: list[Detection], now: float) -> list[Track]:
        unmatched = set(self.tracks)
        for det in sorted(detections, key=lambda d: d.confidence, reverse=True):
            best_id, best_iou = None, self.iou_threshold
            for track_id in unmatched:
                track = self.tracks[track_id]
                if track.kind != det.kind:
                    continue
                overlap = iou(track.box, det.box)
                if overlap >= best_iou:
                    best_id, best_iou = track_id, overlap
            if best_id is None:
                track_id = next(self._ids)
                self.tracks[track_id] = Track(track_id, det.label, det.box, det.confidence, now, now)
            else:
                unmatched.discard(best_id)
                track = self.tracks[best_id]
                track.box, track.last_seen = det.box, now
                track.hits += 1
                track.confidence = max(track.confidence, det.confidence)

        for track_id in [t for t, track in self.tracks.items() if now - track.last_seen > self.max_missing_s]:
            del self.tracks[track_id]
        return list(self.tracks.values())


class EventPolicy:

    def __init__(self, min_hits: int = 2, loiter_s: float = 15.0, cooldown_s: float = 30.0) -> None:
        self.min_hits = min_hits
        self.loiter_s = loiter_s
        self.cooldown_s = cooldown_s
        self.recent: list[list] = []
        self.suppressed = 0

    def events_for(self, tracks: list[Track], now: float) -> list[tuple[str, Track]]:
        self.recent = [r for r in self.recent if now - r[2] < self.cooldown_s]
        events = []
        for track in tracks:
            if track.last_seen != now:
                continue
            if not track.reported and track.hits >= self.min_hits:
                track.reported = True
                if self._recently_reported(track, now):
                    self.suppressed += 1
                else:
                    self.recent.append([track.kind, track.box, now])
                    events.append(("object_detected", track))
            if track.kind == "person" and not track.loiter_reported and now - track.first_seen >= self.loiter_s:
                track.loiter_reported = True
                events.append(("loitering", track))
        return events

    def _recently_reported(self, track: Track, now: float) -> bool:
        for entry in self.recent:
            kind, box, _ = entry
            if kind == track.kind and iou(box, track.box) > 0.3:
                entry[1], entry[2] = track.box, now
                return True
        return False
