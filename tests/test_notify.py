from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from laundry_monitor.models import CompletionEvent
from laundry_monitor.notify import (
    Notifier,
    notification_payload,
    transfer_reminder_payload,
    validation_prompt_payload,
)


def test_notification_payload_has_stable_mobile_tags() -> None:
    payload = notification_payload(_event())

    assert payload["title"] == "Washer finished"
    assert payload["data"] == {
        "tag": "laundry-monitor-washer-complete",
        "group": "laundry-monitor",
    }


def test_notification_payload_uses_appliance_slug() -> None:
    payload = notification_payload(_event(appliance_name="Dryer", appliance_slug="dryer"))

    assert payload["title"] == "Dryer finished"
    assert payload["data"]["tag"] == "laundry-monitor-dryer-complete"


def test_transfer_reminder_payload_has_snooze_and_done_buttons() -> None:
    payload = transfer_reminder_payload(
        washer_finished_at=_now(),
        snooze_action="LAUNDRY_TRANSFER_SNOOZE::token",
        done_action="LAUNDRY_TRANSFER_DONE::token",
    )

    assert payload["title"] == "Washer load still waiting"
    assert [button["title"] for button in payload["data"]["actions"]] == [
        "Snooze 2h",
        "Done",
    ]


def test_validation_prompt_payload_has_yes_and_no_buttons() -> None:
    payload = validation_prompt_payload(
        title="Washer started?",
        yes_action="LAUNDRY_VALIDATE_YES::event",
        no_action="LAUNDRY_VALIDATE_NO::event",
    )

    assert payload["title"] == "Washer started?"
    assert [button["title"] for button in payload["data"]["actions"]] == ["Yes", "No"]


def test_notifier_sends_to_all_configured_services() -> None:
    caller = FakeCaller()
    notifier = Notifier(
        caller,
        ("notify.mobile_app_joe", "notify.mobile_app_jess"),
    )

    asyncio.run(notifier.send_cycle_complete(_event()))

    assert [call[:2] for call in caller.calls] == [
        ("notify", "mobile_app_joe"),
        ("notify", "mobile_app_jess"),
    ]


def test_notifier_sends_transfer_reminder_to_all_configured_services() -> None:
    caller = FakeCaller()
    notifier = Notifier(
        caller,
        ("notify.mobile_app_joe", "notify.mobile_app_jess"),
    )

    asyncio.run(
        notifier.send_transfer_reminder(
            washer_finished_at=_now(),
            buttons=[
                {"action": "LAUNDRY_TRANSFER_SNOOZE::token"},
                {"action": "LAUNDRY_TRANSFER_DONE::token"},
            ],
        )
    )

    assert [call[:2] for call in caller.calls] == [
        ("notify", "mobile_app_joe"),
        ("notify", "mobile_app_jess"),
    ]


class FakeCaller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def call_service(self, domain: str, service: str, service_data: dict) -> dict:
        self.calls.append((domain, service, service_data))
        return {"ok": True}


def _event(
    *,
    appliance_name: str = "Washer",
    appliance_slug: str = "washer",
) -> CompletionEvent:
    now = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)
    return CompletionEvent(
        appliance_name=appliance_name,
        appliance_slug=appliance_slug,
        started_at=now,
        completed_at=now,
        peak_watts=724.1,
        runtime_minutes=65.7,
    )


def _now() -> datetime:
    return datetime(2026, 6, 14, 18, 0, tzinfo=timezone.utc)
