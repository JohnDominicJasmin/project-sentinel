import asyncio
from datetime import datetime, timezone

from app.models import Event
from app.store import AlarmStore
from app.triage.llm import InvalidOutput, LLMResponse, RateLimited, TriageResult
from app.triage.rules import rule_severity
from app.triage.service import TriageService

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


class FakeTriager:
    model = "fake-model"

    def __init__(self, *behaviours):
        self.behaviours = list(behaviours)
        self.calls = 0

    async def triage(self, events):
        self.calls += 1
        behaviour = self.behaviours.pop(0) if self.behaviours else "ok"
        if behaviour == "junk":
            raise InvalidOutput("junk", 100, 20)
        if behaviour == "429":
            raise RateLimited("429")
        if behaviour == "slow":
            await asyncio.sleep(1)
        if behaviour == "drop_first":
            events = events[1:]
        results = [
            TriageResult(event_id=e.event_id, severity="warning", verdict="uncertain", summary="Checked.", action="Review.")
            for e in events
        ]
        return LLMResponse(results, input_tokens=1000, output_tokens=200)


def make_service(triager, **kwargs):
    store = AlarmStore()
    options = dict(budget_usd=1.0, price_input_per_1m=1.0, price_output_per_1m=5.0, timeout_s=0.2)
    options.update(kwargs)
    return store, TriageService(store, triager, **options)


def add(store, service, event_id, kind="door_forced", confidence=0.5):
    event = Event(event_id=event_id, site_id="site-101", zone="lobby", type=kind, source="sensor",
                  confidence=confidence, timestamp=NOW, received_at=NOW)
    alarm = store.add(event, *rule_severity(event))
    service.submit(alarm)
    return alarm


def drain(service):
    batch = []
    while not service.queue.empty():
        batch.append(service.queue.get_nowait())
    asyncio.run(service.process(batch))


def test_successful_triage_is_applied():
    store, service = make_service(FakeTriager())
    add(store, service, "a")
    drain(service)
    alarm = store.get("a")
    assert alarm.triage_status == "ai" and alarm.severity_source == "ai"
    assert alarm.ai.summary == "Checked." and alarm.ai.model == "fake-model"
    assert service.metrics.spent_usd == 1000 / 1e6 * 1.0 + 200 / 1e6 * 5.0


def test_life_safety_is_never_downgraded():
    store, service = make_service(FakeTriager())
    add(store, service, "fire", kind="fire_alarm", confidence=0.3)
    drain(service)
    alarm = store.get("fire")
    assert alarm.severity == "critical" and alarm.severity_source == "rules"
    assert alarm.ai.severity == "warning"
    assert "life-safety" in alarm.triage_note


def test_junk_is_retried_once():
    triager = FakeTriager("junk", "ok")
    store, service = make_service(triager)
    add(store, service, "a")
    drain(service)
    assert triager.calls == 2
    assert store.get("a").triage_status == "ai"


def test_junk_twice_falls_back_to_rules():
    store, service = make_service(FakeTriager("junk", "junk"))
    add(store, service, "a")
    drain(service)
    alarm = store.get("a")
    assert alarm.triage_status == "rules" and "invalid output" in alarm.triage_note
    assert service.metrics.input_tokens == 200


def test_timeouts_pause_the_ai_after_repeated_failures():
    triager = FakeTriager("slow", "slow", "slow")
    store, service = make_service(triager, failure_threshold=3)
    for i in range(3):
        add(store, service, f"e{i}")
        drain(service)
    assert "timed out" in store.get("e0").triage_note
    assert service.state == "paused"

    add(store, service, "after")
    drain(service)
    assert triager.calls == 3
    assert "paused" in store.get("after").triage_note


def test_rate_limit_pauses_immediately():
    triager = FakeTriager("429")
    store, service = make_service(triager)
    add(store, service, "a")
    drain(service)
    add(store, service, "b")
    drain(service)
    assert "rate limited" in store.get("a").triage_note
    assert "paused" in store.get("b").triage_note
    assert triager.calls == 1


def test_budget_cap_stops_ai_calls():
    triager = FakeTriager()
    store, service = make_service(triager, budget_usd=0.001)
    add(store, service, "a")
    drain(service)
    add(store, service, "b")
    drain(service)
    assert store.get("a").triage_status == "ai"
    assert "budget" in store.get("b").triage_note
    assert triager.calls == 1 and service.state == "budget_reached"


def test_missing_result_falls_back_for_that_alarm_only():
    store, service = make_service(FakeTriager("drop_first"))
    add(store, service, "a")
    add(store, service, "b")
    drain(service)
    assert store.get("a").triage_status == "rules"
    assert store.get("b").triage_status == "ai"


def test_ai_off_marks_rules_immediately():
    store, service = make_service(None)
    add(store, service, "a")
    assert store.get("a").triage_note == "AI off, rules only"
    assert service.queue.empty()


def test_backlog_is_shed_to_rules():
    store, service = make_service(FakeTriager(), max_backlog=1)
    add(store, service, "a")
    add(store, service, "b")
    assert "backlog" in store.get("b").triage_note


def test_critical_alarms_are_triaged_first():
    store, service = make_service(FakeTriager())
    add(store, service, "motion", kind="motion_detected")
    add(store, service, "panic", kind="panic_button")
    first = service.queue.get_nowait()
    assert first[2] == "panic"


def test_resolved_alarms_are_not_sent_to_the_ai():
    triager = FakeTriager()
    store, service = make_service(triager)
    add(store, service, "a")
    store.resolve("a")
    drain(service)
    assert triager.calls == 0
