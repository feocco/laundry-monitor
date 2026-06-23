from __future__ import annotations

from datetime import datetime, timedelta, timezone

from laundry_monitor.config import ApplianceConfig, ThresholdConfig
from laundry_monitor.detector import CycleDetector
from laundry_monitor.models import LifecycleEventType, Phase, PowerSample
from laundry_monitor.runtime_state import ApplianceRuntimeState


def test_normal_washer_cycle_completes_once() -> None:
    detector = _detector()
    start = _time()
    event = None
    for minute in range(0, 61, 5):
        event = detector.observe(_sample(start, minute, 220.0 if minute < 55 else 300.0))
    for minute in (62, 70, 75, 80):
        event = detector.observe(_sample(start, minute, 1.0))

    assert event is not None
    assert event.runtime_minutes == 80
    assert event.peak_watts == 300.0
    assert detector.state.phase == Phase.COMPLETE
    assert [item.event_type for item in detector.drain_lifecycle_events()] == [
        LifecycleEventType.WASHER_STARTED,
        LifecycleEventType.WASHER_FINISHED,
    ]
    assert detector.should_notify(event)
    detector.mark_notified(event)
    assert not detector.should_notify(event)


def test_pause_under_tolerance_does_not_complete_cycle() -> None:
    detector = _detector()
    start = _time()
    for minute in range(0, 31, 5):
        detector.observe(_sample(start, minute, 250.0))
    event = None
    for minute in (35, 40, 45):
        event = detector.observe(_sample(start, minute, 1.0))

    assert event is None
    assert detector.state.phase == Phase.RUNNING

    detector.observe(_sample(start, 48, 280.0))
    event = detector.observe(_sample(start, 49, 1.0))
    assert event is None


def test_idle_baseline_and_brief_spikes_do_not_start_cycle() -> None:
    detector = _detector()
    start = _time()
    for minute, watts in ((0, 0.4), (5, 1.2), (10, 45.0), (11, 0.6), (30, 0.4)):
        detector.observe(_sample(start, minute, watts))

    assert detector.state.phase == Phase.IDLE
    assert detector.state.cycle_started_at is None
    assert detector.drain_lifecycle_events() == []


def test_observed_dryer_cycle_emits_lifecycle_events() -> None:
    detector = _detector(name="Dryer", entity="sensor.dryer_plug_power", slug="dryer")
    start = _time()
    event = None

    for minute, watts in (
        (0, 0.3),
        (1, 23.3),
        (5, 580.0),
        (10, 725.7),
        (30, 238.0),
        (60, 237.4),
        (63, 0.7),
        (70, 0.3),
        (74, 0.0),
    ):
        event = detector.observe(_sample(start, minute, watts))

    assert event is not None
    assert event.appliance_slug == "dryer"
    assert event.appliance_name == "Dryer"
    assert round(event.runtime_minutes) == 64
    assert event.peak_watts == 725.7
    assert [item.event_type for item in detector.drain_lifecycle_events()] == [
        LifecycleEventType.DRYER_STARTED,
        LifecycleEventType.DRYER_FINISHED,
    ]


def test_unavailable_state_does_not_advance_cycle() -> None:
    detector = _detector()
    detector.observe_invalid("unavailable")

    assert detector.state.phase == Phase.IDLE
    assert detector.state.last_invalid_state == "unavailable"


def _detector(
    *,
    name: str = "Washer",
    entity: str = "sensor.smartthings_outletv4_power",
    slug: str = "washer",
) -> CycleDetector:
    return CycleDetector(
        ApplianceConfig(name=name, power_entity=entity, slug=slug),
        ThresholdConfig(),
        ApplianceRuntimeState(),
    )


def _sample(start: datetime, minutes: int, watts: float) -> PowerSample:
    return PowerSample(timestamp=start + timedelta(minutes=minutes), watts=watts)


def _time() -> datetime:
    return datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)
