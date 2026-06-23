from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from laundry_monitor.config import ApplianceConfig, Settings, ThresholdConfig
from laundry_monitor.models import EntityState, LifecycleEventType, PowerSample
from laundry_monitor.monitor import LaundryMonitor
from laundry_monitor.notify import notification_payload


def test_status_payload_reports_washer_state(tmp_path) -> None:
    monitor = LaundryMonitor(_settings(tmp_path))
    monitor.detectors["washer"].observe(PowerSample(_now(), 1.2))
    monitor.detectors["dryer"].observe(PowerSample(_now(), 0.0))

    payload = monitor.status_payload(stale_after_seconds=900)

    assert payload["service"] == "laundry-monitor"
    assert payload["status"] == "ok"
    assert payload["appliances"]["washer"]["phase"] == "idle"
    assert payload["appliances"]["washer"]["entity_id"] == "sensor.smartthings_outletv4_power"
    assert payload["appliances"]["washer"]["entity_fresh"] is True
    assert payload["appliances"]["dryer"]["entity_id"] == "sensor.dryer_plug_power"
    assert payload["washer_transfer"]["waiting"] is False


def test_status_payload_degrades_for_invalid_state(tmp_path) -> None:
    monitor = LaundryMonitor(_settings(tmp_path))
    monitor.detectors["washer"].observe_invalid("unavailable")

    payload = monitor.status_payload(stale_after_seconds=900)

    assert payload["status"] == "degraded"
    assert payload["appliances"]["washer"]["last_invalid_state"] == "unavailable"


def test_status_payload_keeps_global_ok_for_stale_idle_appliance(tmp_path) -> None:
    monitor = LaundryMonitor(_settings(tmp_path))
    old_sample = _now() - timedelta(hours=2)
    monitor.detectors["washer"].observe(PowerSample(_now(), 1.2))
    monitor.detectors["dryer"].observe(PowerSample(old_sample, 0.0))

    payload = monitor.status_payload(stale_after_seconds=900)

    assert payload["status"] == "ok"
    assert payload["appliances"]["dryer"]["entity_fresh"] is False


def test_washer_finish_creates_waiting_state_and_reminder(tmp_path) -> None:
    monitor = LaundryMonitor(_settings(tmp_path))
    monitor.notifier = FakeNotifier()
    start = _time()

    _run_cycle(monitor, "sensor.smartthings_outletv4_power", start, "Washer")
    assert monitor.state.washer_transfer.waiting_since is not None
    reminder_due_at = start + timedelta(minutes=80, hours=6)
    assert monitor.state.washer_transfer.next_reminder_at == reminder_due_at

    asyncio.run(monitor.check_scheduled_workflows(reminder_due_at + timedelta(minutes=1)))

    assert len(monitor.notifier.transfer_reminders) == 1
    reminder = monitor.notifier.transfer_reminders[0]
    assert reminder["washer_finished_at"] == start + timedelta(minutes=80)
    assert [button["title"] for button in reminder["buttons"]] == ["Snooze 2h", "Done"]
    assert monitor.state.washer_transfer.reminder_sent_at == reminder_due_at + timedelta(minutes=1)
    assert monitor.state.washer_transfer.next_reminder_at is None


def test_dryer_start_clears_waiting_state(tmp_path) -> None:
    monitor = LaundryMonitor(_settings(tmp_path))
    start = _time()

    _run_cycle(monitor, "sensor.smartthings_outletv4_power", start, "Washer")
    assert monitor.state.washer_transfer.waiting_since is not None

    asyncio.run(
        monitor.observe_entity_state(
            EntityState(
                entity_id="sensor.dryer_plug_power",
                state="45.0",
                last_updated=start + timedelta(hours=2),
            )
        )
    )

    assert monitor.state.washer_transfer.cleared_at == start + timedelta(hours=2)
    assert monitor.state.washer_transfer.waiting_since is None


def test_reminder_actions_snooze_and_done(tmp_path) -> None:
    monitor = LaundryMonitor(_settings(tmp_path))
    start = _time()
    _run_cycle(monitor, "sensor.smartthings_outletv4_power", start, "Washer")
    token = monitor.state.washer_transfer.reminder_token
    assert token is not None

    monitor.handle_notification_action(
        {
            "event_type": "mobile_app_notification_action",
            "data": {"action": f"LAUNDRY_TRANSFER_SNOOZE::{token}"},
        },
        now=start + timedelta(hours=7),
    )
    assert monitor.state.washer_transfer.next_reminder_at == start + timedelta(hours=9)

    monitor.handle_notification_action(
        {
            "event_type": "mobile_app_notification_action",
            "data": {"action": f"LAUNDRY_TRANSFER_DONE::{token}"},
        },
        now=start + timedelta(hours=8),
    )
    assert monitor.state.washer_transfer.waiting_since is None
    assert monitor.state.washer_transfer.cleared_at == start + timedelta(hours=8)


def test_validation_prompt_and_response_are_recorded(tmp_path) -> None:
    monitor = LaundryMonitor(_settings(tmp_path))
    monitor.notifier = FakeNotifier()
    start = _time()

    for minute in (0, 10):
        asyncio.run(
            monitor.observe_entity_state(
                EntityState(
                    entity_id="sensor.smartthings_outletv4_power",
                    state="220.0",
                    last_updated=start + timedelta(minutes=minute),
                )
            )
        )

    assert monitor.notifier.validation_prompts
    event = monitor.state.lifecycle_events[-1]
    assert event.event_type == LifecycleEventType.WASHER_STARTED
    prompt = monitor.notifier.validation_prompts[-1]
    assert prompt["event_id"] == event.event_id
    assert [button["title"] for button in prompt["buttons"]] == ["Yes", "No"]

    monitor.handle_notification_action(
        {
            "event_type": "mobile_app_notification_action",
            "data": {"action": f"LAUNDRY_VALIDATE_YES::{event.event_id}"},
        },
        now=start + timedelta(minutes=11),
    )

    assert monitor.state.validation_responses[event.event_id].response == "yes"


def _settings(tmp_path) -> Settings:
    return Settings(
        service_name="laundry-monitor",
        host="127.0.0.1",
        port=0,
        log_level="INFO",
        ha_url="https://ha.example",
        ha_token="token",
        appliances=(
            ApplianceConfig(
                name="Washer",
                power_entity="sensor.smartthings_outletv4_power",
                slug="washer",
                notify_enabled=True,
            ),
            ApplianceConfig(
                name="Dryer",
                power_entity="sensor.dryer_plug_power",
                slug="dryer",
                notify_enabled=False,
            ),
        ),
        notify_services=("notify.mobile_app_joe", "notify.mobile_app_jess"),
        validation_notify_services=("notify.mobile_app_joe",),
        lifecycle_validation_enabled=True,
        lifecycle_validation_events=(
            LifecycleEventType.WASHER_STARTED,
            LifecycleEventType.WASHER_FINISHED,
            LifecycleEventType.DRYER_STARTED,
            LifecycleEventType.DRYER_FINISHED,
        ),
        thresholds=ThresholdConfig(),
        transfer_reminder_hours=6,
        transfer_snooze_hours=2,
        state_path=tmp_path / "state.json",
        dry_run=True,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _time() -> datetime:
    return datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)


def _run_cycle(
    monitor: LaundryMonitor,
    entity_id: str,
    start: datetime,
    appliance_name: str,
) -> None:
    for minute in range(0, 61, 5):
        asyncio.run(
            monitor.observe_entity_state(
                EntityState(
                    entity_id=entity_id,
                    state="220.0",
                    last_updated=start + timedelta(minutes=minute),
                )
            )
        )
    for minute in (62, 70, 75, 80):
        asyncio.run(
            monitor.observe_entity_state(
                EntityState(
                    entity_id=entity_id,
                    state="1.0",
                    last_updated=start + timedelta(minutes=minute),
                )
            )
        )
    assert monitor.state.appliances[appliance_name.lower()].phase == "complete"


class FakeNotifier:
    def __init__(self) -> None:
        self.completions: list[dict] = []
        self.transfer_reminders: list[dict] = []
        self.validation_prompts: list[dict] = []

    async def send_cycle_complete(self, event) -> None:
        self.completions.append(notification_payload(event))

    async def send_transfer_reminder(
        self,
        *,
        washer_finished_at: datetime,
        buttons: list[dict],
    ) -> None:
        self.transfer_reminders.append(
            {"washer_finished_at": washer_finished_at, "buttons": buttons}
        )

    async def send_validation_prompt(self, *, event, buttons: list[dict]) -> None:
        self.validation_prompts.append({"event_id": event.event_id, "buttons": buttons})
