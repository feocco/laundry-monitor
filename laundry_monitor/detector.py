from __future__ import annotations

from datetime import timedelta

from .config import ApplianceConfig, ThresholdConfig
from .models import CompletionEvent, LifecycleEvent, LifecycleEventType, Phase, PowerSample
from .runtime_state import ApplianceRuntimeState


class CycleDetector:
    def __init__(
        self,
        appliance: ApplianceConfig,
        thresholds: ThresholdConfig,
        state: ApplianceRuntimeState,
    ) -> None:
        self.appliance = appliance
        self.thresholds = thresholds
        self.state = state
        self._lifecycle_events: list[LifecycleEvent] = []

    def observe(self, sample: PowerSample) -> CompletionEvent | None:
        self.state.last_sample_at = sample.timestamp
        self.state.last_watts = sample.watts
        self.state.last_invalid_state = None
        if sample.watts > self.thresholds.idle_watts:
            self.state.last_above_idle_at = sample.timestamp
            self.state.quiet_since = None

        if self.state.phase is Phase.IDLE:
            self._observe_idle(sample)
            return None
        if self.state.phase is Phase.COMPLETE and sample.watts > self.thresholds.start_watts:
            self._reset_for_new_cycle()
            self._observe_idle(sample)
            return None
        if self.state.phase is Phase.RUNNING:
            return self._observe_running(sample)
        return None

    def observe_invalid(self, raw_state: str) -> None:
        self.state.last_invalid_state = raw_state

    def should_notify(self, event: CompletionEvent) -> bool:
        last_cycle = self.state.last_notification_cycle_completed_at
        if last_cycle == event.completed_at:
            return False
        last_sent = self.state.last_notification_at
        if last_sent is None:
            return True
        cooldown = timedelta(minutes=self.thresholds.duplicate_cooldown_minutes)
        return event.completed_at - last_sent >= cooldown

    def mark_notified(self, event: CompletionEvent) -> None:
        self.state.last_notification_at = event.completed_at
        self.state.last_notification_cycle_completed_at = event.completed_at

    def drain_lifecycle_events(self) -> list[LifecycleEvent]:
        events = list(self._lifecycle_events)
        self._lifecycle_events.clear()
        return events

    def _observe_idle(self, sample: PowerSample) -> None:
        cutoff = sample.timestamp - timedelta(minutes=self.thresholds.activity_window_minutes)
        self.state.candidate_samples = [
            existing for existing in self.state.candidate_samples if existing.timestamp >= cutoff
        ]
        if sample.watts > self.thresholds.active_watts:
            self.state.candidate_samples.append(sample)
        if not self._has_start_signal():
            return
        self.state.phase = Phase.RUNNING
        self.state.cycle_started_at = self.state.candidate_samples[0].timestamp
        self.state.peak_watts = max(existing.watts for existing in self.state.candidate_samples)
        self.state.last_above_idle_at = sample.timestamp
        self.state.quiet_since = None
        self._append_lifecycle_event(
            _event_type(self.appliance.slug, started=True),
            occurred_at=self.state.cycle_started_at,
            peak_watts=self.state.peak_watts,
        )

    def _observe_running(self, sample: PowerSample) -> CompletionEvent | None:
        self.state.peak_watts = max(self.state.peak_watts, sample.watts)
        if sample.watts < self.thresholds.idle_watts:
            if self.state.quiet_since is None:
                self.state.quiet_since = sample.timestamp
        else:
            self.state.quiet_since = None

        if not self._cycle_is_valid(sample):
            return None
        if self.state.quiet_since is None:
            return None
        quiet_for = sample.timestamp - self.state.quiet_since
        since_active = sample.timestamp - (self.state.last_above_idle_at or self.state.quiet_since)
        if quiet_for < timedelta(minutes=self.thresholds.quiet_minutes):
            return None
        if (
            self.appliance.slug != "dryer"
            and since_active < timedelta(minutes=self.thresholds.pause_tolerance_minutes)
        ):
            return None

        self.state.phase = Phase.COMPLETE
        self.state.cycle_completed_at = sample.timestamp
        event = CompletionEvent(
            appliance_slug=self.appliance.slug,
            appliance_name=self.appliance.name,
            started_at=self.state.cycle_started_at or sample.timestamp,
            completed_at=sample.timestamp,
            peak_watts=self.state.peak_watts,
            runtime_minutes=self._runtime_minutes(sample),
        )
        self._append_lifecycle_event(
            _event_type(self.appliance.slug, started=False),
            occurred_at=sample.timestamp,
            peak_watts=event.peak_watts,
            runtime_minutes=event.runtime_minutes,
        )
        return event

    def _has_start_signal(self) -> bool:
        samples = self.state.candidate_samples
        if len(samples) < 2:
            return False
        if max(sample.watts for sample in samples) < self.thresholds.start_watts:
            return False
        active_span = samples[-1].timestamp - samples[0].timestamp
        return active_span >= timedelta(minutes=self.thresholds.minimum_activity_minutes)

    def _cycle_is_valid(self, sample: PowerSample) -> bool:
        return (
            self.state.cycle_started_at is not None
            and self._runtime_minutes(sample) >= self.thresholds.minimum_cycle_minutes
            and self.state.peak_watts >= self.thresholds.minimum_peak_watts
        )

    def _runtime_minutes(self, sample: PowerSample) -> float:
        if self.state.cycle_started_at is None:
            return 0.0
        return (sample.timestamp - self.state.cycle_started_at).total_seconds() / 60

    def _reset_for_new_cycle(self) -> None:
        self.state.phase = Phase.IDLE
        self.state.candidate_samples = []
        self.state.cycle_started_at = None
        self.state.quiet_since = None
        self.state.peak_watts = 0.0

    def _append_lifecycle_event(
        self,
        event_type: LifecycleEventType,
        *,
        occurred_at,
        peak_watts: float | None = None,
        runtime_minutes: float | None = None,
    ) -> None:
        self._lifecycle_events.append(
            LifecycleEvent(
                event_id=f"{self.appliance.slug}-{event_type.value}-{occurred_at.isoformat()}",
                event_type=event_type,
                appliance_slug=self.appliance.slug,
                appliance_name=self.appliance.name,
                occurred_at=occurred_at,
                peak_watts=peak_watts,
                runtime_minutes=runtime_minutes,
            )
        )


def _event_type(appliance_slug: str, *, started: bool) -> LifecycleEventType:
    if appliance_slug == "dryer":
        return (
            LifecycleEventType.DRYER_STARTED
            if started
            else LifecycleEventType.DRYER_FINISHED
        )
    return (
        LifecycleEventType.WASHER_STARTED
        if started
        else LifecycleEventType.WASHER_FINISHED
    )


WasherDetector = CycleDetector
