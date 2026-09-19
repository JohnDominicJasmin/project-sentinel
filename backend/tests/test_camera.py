import numpy as np

from app.camera.detector import Detection, non_max_suppression
from app.camera.tracking import EventPolicy, Tracker, iou


def det(label, box, confidence=0.8):
    return Detection(label=label, confidence=confidence, box=box)


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 5, 5)) == 0.0
    assert round(iou((0, 0, 10, 10), (5, 0, 10, 10)), 2) == 0.33


def test_nms_keeps_the_best_of_overlapping_boxes():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=float)
    scores = np.array([0.6, 0.9, 0.7])
    assert non_max_suppression(boxes, scores, 0.5) == [1, 2]


def test_tracker_keeps_identity_while_an_object_moves():
    tracker = Tracker()
    [first] = tracker.update([det("person", (100, 100, 40, 80))], now=0.0)
    [second] = tracker.update([det("person", (110, 102, 40, 80))], now=0.25)
    assert first.track_id == second.track_id and second.hits == 2


def test_tracker_allows_label_flips_within_the_same_kind():
    tracker = Tracker()
    [first] = tracker.update([det("car", (0, 0, 100, 50))], now=0.0)
    [second] = tracker.update([det("truck", (5, 0, 100, 50))], now=0.25)
    assert first.track_id == second.track_id


def test_tracker_forgets_objects_that_left():
    tracker = Tracker(max_missing_s=1.0)
    tracker.update([det("person", (0, 0, 10, 10))], now=0.0)
    assert tracker.update([], now=2.0) == []


def test_one_alarm_per_object_after_it_is_confirmed():
    tracker, policy = Tracker(), EventPolicy(min_hits=2)
    box = (100, 100, 40, 80)
    assert policy.events_for(tracker.update([det("person", box)], 0.0), 0.0) == []
    events = policy.events_for(tracker.update([det("person", box)], 0.25), 0.25)
    assert [e[0] for e in events] == ["object_detected"]
    assert policy.events_for(tracker.update([det("person", box)], 0.5), 0.5) == []


def test_flickering_object_does_not_alarm_twice():
    tracker, policy = Tracker(max_missing_s=0.5), EventPolicy(min_hits=2, cooldown_s=30)
    box = (100, 100, 40, 80)
    for t in (0.0, 0.25):
        policy.events_for(tracker.update([det("person", box)], t), t)
    tracker.update([], 2.0)
    for t in (2.25, 2.5):
        assert policy.events_for(tracker.update([det("person", box)], t), t) == []
    assert policy.suppressed == 1


def test_person_who_stays_triggers_one_loitering_alarm():
    tracker, policy = Tracker(), EventPolicy(min_hits=2, loiter_s=10)
    box = (100, 100, 40, 80)
    kinds = []
    for step in range(50):
        t = step * 0.25
        kinds += [e[0] for e in policy.events_for(tracker.update([det("person", box)], t), t)]
    assert kinds == ["object_detected", "loitering"]


def test_vehicles_never_loiter():
    tracker, policy = Tracker(), EventPolicy(min_hits=2, loiter_s=1)
    kinds = []
    for step in range(20):
        t = step * 0.25
        kinds += [e[0] for e in policy.events_for(tracker.update([det("car", (0, 0, 100, 50))], t), t)]
    assert kinds == ["object_detected"]
