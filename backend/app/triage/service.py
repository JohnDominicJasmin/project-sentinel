import asyncio
import itertools
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..models import SEVERITY_RANK, AiTriage, Alarm, Event
from ..store import AlarmStore
from .llm import InvalidOutput, LLMResponse, LLMUnavailable, RateLimited, TriageResult, Triager
from .rules import ALWAYS_CRITICAL

log = logging.getLogger("sentinel.triage")


@dataclass
class TriageMetrics:
    calls: int = 0
    failed_calls: int = 0
    ai_triaged: int = 0
    fallbacks: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    spent_usd: float = 0.0
    latencies_ms: deque = field(default_factory=lambda: deque(maxlen=200))
    end_to_end_ms: deque = field(default_factory=lambda: deque(maxlen=200))


def percentile(values, p: float) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    return int(ordered[min(len(ordered) - 1, int(p * len(ordered)))])


class TriageService:
    """Runs AI triage in the background so a slow or failing model never blocks ingestion.

    Alarms are queued most-severe first and sent in small batches. Every
    failure path (timeout, rate limit, junk output, budget, backlog) leaves
    the alarm on its rule-based severity with a note saying why.
    """

    def __init__(
        self,
        store: AlarmStore,
        triager: Optional[Triager],
        *,
        budget_usd: float,
        price_input_per_1m: float,
        price_output_per_1m: float,
        timeout_s: float = 10.0,
        workers: int = 3,
        batch_max: int = 8,
        max_backlog: int = 300,
        max_wait_s: float = 60.0,
        pause_s: float = 30.0,
        failure_threshold: int = 3,
    ) -> None:
        self.store = store
        self.triager = triager
        self.budget_usd = budget_usd
        self.price_input = price_input_per_1m / 1_000_000
        self.price_output = price_output_per_1m / 1_000_000
        self.timeout_s = timeout_s
        self.workers = workers
        self.batch_max = batch_max
        self.max_backlog = max_backlog
        self.max_wait_s = max_wait_s
        self.pause_s = pause_s
        self.failure_threshold = failure_threshold
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.metrics = TriageMetrics()
        self._order = itertools.count()
        self._paused_until = 0.0
        self._pause_reason = ""
        self._consecutive_failures = 0

    @property
    def state(self) -> str:
        if self.triager is None:
            return "off"
        if self.metrics.spent_usd >= self.budget_usd:
            return "budget_reached"
        if time.monotonic() < self._paused_until:
            return "paused"
        return "on"

    def stats(self) -> dict:
        m = self.metrics
        return {
            "state": self.state,
            "model": self.triager.model if self.triager else None,
            "chaos": getattr(self.triager, "mode", "off"),
            "pause_reason": self._pause_reason if self.state == "paused" else None,
            "queue_depth": self.queue.qsize(),
            "calls": m.calls,
            "failed_calls": m.failed_calls,
            "ai_triaged": m.ai_triaged,
            "fallbacks": m.fallbacks,
            "input_tokens": m.input_tokens,
            "output_tokens": m.output_tokens,
            "spent_usd": round(m.spent_usd, 5),
            "budget_usd": self.budget_usd,
            "latency_p50_ms": percentile(m.latencies_ms, 0.5),
            "latency_p95_ms": percentile(m.latencies_ms, 0.95),
            "end_to_end_p50_ms": percentile(m.end_to_end_ms, 0.5),
            "end_to_end_p95_ms": percentile(m.end_to_end_ms, 0.95),
        }

    def submit(self, alarm: Alarm) -> None:
        event_id = alarm.event.event_id
        if self.triager is None:
            self._fallback([event_id], "AI off, rules only")
            return
        if self.queue.qsize() >= self.max_backlog:
            self._fallback([event_id], "AI skipped: backlog too deep")
            return
        self.queue.put_nowait((SEVERITY_RANK[alarm.severity], next(self._order), event_id, time.monotonic()))

    async def run(self) -> None:
        if self.triager is None:
            return
        await asyncio.gather(*(self._worker() for _ in range(self.workers)))

    async def _worker(self) -> None:
        while True:
            batch = [await self.queue.get()]
            while len(batch) < self.batch_max and not self.queue.empty():
                batch.append(self.queue.get_nowait())
            try:
                await self.process(batch)
            except Exception:
                log.exception("triage worker error")
                self._fallback([item[2] for item in batch], "AI error, rules only")

    async def process(self, batch: list[tuple]) -> None:
        now = time.monotonic()
        ids: list[str] = []
        for _, _, event_id, queued_at in batch:
            alarm = self.store.get(event_id)
            if alarm is None or alarm.status == "resolved":
                continue
            if now - queued_at > self.max_wait_s:
                self._fallback([event_id], "AI skipped: waited too long")
                continue
            ids.append(event_id)
        if not ids:
            return

        blocked = self._blocked_reason()
        if blocked:
            self._fallback(ids, blocked)
            return

        events: list[Event] = [self.store.get(i).event for i in ids]
        started = time.monotonic()
        try:
            response = await self._call(events)
        except RateLimited:
            self._pause("AI paused: rate limited")
            self._fallback(ids, "AI rate limited, rules only")
            return
        except LLMUnavailable as exc:
            self._record_failure(str(exc))
            self._fallback(ids, f"{exc}, rules only")
            return
        except InvalidOutput:
            self._record_failure("invalid AI output")
            self._fallback(ids, "AI returned invalid output, rules only")
            return

        latency_ms = int((time.monotonic() - started) * 1000)
        self._consecutive_failures = 0
        self.metrics.latencies_ms.append(latency_ms)
        by_id = {r.event_id: r for r in response.results}
        missing = []
        for event_id in ids:
            result = by_id.get(event_id)
            if result is None:
                missing.append(event_id)
            else:
                self._apply(event_id, result, latency_ms)
        if missing:
            self._fallback(missing, "AI skipped this alarm, rules only")

    async def _call(self, events: list[Event]) -> LLMResponse:
        try:
            return await self._attempt(events)
        except InvalidOutput:
            if self._blocked_reason():
                raise
            log.warning("AI returned invalid output, retrying once")
            return await self._attempt(events)

    async def _attempt(self, events: list[Event]) -> LLMResponse:
        self.metrics.calls += 1
        try:
            response = await asyncio.wait_for(self.triager.triage(events), self.timeout_s)
        except TimeoutError as exc:
            self.metrics.failed_calls += 1
            raise LLMUnavailable("AI timed out") from exc
        except InvalidOutput as exc:
            self.metrics.failed_calls += 1
            self._charge(exc.input_tokens, exc.output_tokens)
            raise
        except Exception:
            self.metrics.failed_calls += 1
            raise
        self._charge(response.input_tokens, response.output_tokens)
        return response

    def _apply(self, event_id: str, result: TriageResult, latency_ms: int) -> None:
        alarm = self.store.get(event_id)
        if alarm is None:
            return
        severity, source, note = result.severity, "ai", None
        if alarm.event.type in ALWAYS_CRITICAL and result.severity != "critical":
            severity, source = "critical", "rules"
            note = f"AI rated this {result.severity}. Kept critical by safety rule."
        ai = AiTriage(
            severity=result.severity,
            verdict=result.verdict,
            summary=result.summary,
            action=result.action,
            model=self.triager.model,
            latency_ms=latency_ms,
        )
        self.store.update(
            event_id, severity=severity, severity_source=source, triage_status="ai", triage_note=note, ai=ai
        )
        self.metrics.ai_triaged += 1
        self.metrics.end_to_end_ms.append((datetime.now(timezone.utc) - alarm.event.received_at).total_seconds() * 1000)

    def _fallback(self, ids: list[str], note: str) -> None:
        for event_id in ids:
            if self.store.update(event_id, triage_status="rules", triage_note=note):
                self.metrics.fallbacks += 1

    def _blocked_reason(self) -> Optional[str]:
        if self.metrics.spent_usd >= self.budget_usd:
            return "AI budget reached, rules only"
        if time.monotonic() < self._paused_until:
            return f"{self._pause_reason}, rules only"
        return None

    def _pause(self, reason: str) -> None:
        self._paused_until = time.monotonic() + self.pause_s
        self._pause_reason = reason
        log.warning("%s for %.0fs", reason, self.pause_s)

    def _record_failure(self, reason: str) -> None:
        self._consecutive_failures += 1
        log.warning("AI call failed: %s (%d in a row)", reason, self._consecutive_failures)
        if self._consecutive_failures >= self.failure_threshold:
            self._consecutive_failures = 0
            self._pause(f"AI paused after {self.failure_threshold} failures")

    def _charge(self, input_tokens: int, output_tokens: int) -> None:
        self.metrics.input_tokens += input_tokens
        self.metrics.output_tokens += output_tokens
        self.metrics.spent_usd += input_tokens * self.price_input + output_tokens * self.price_output
