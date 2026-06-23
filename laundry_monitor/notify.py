from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import CompletionEvent, LifecycleEvent


class ServiceCaller(Protocol):
    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict,
    ) -> dict:
        ...


class Notifier:
    def __init__(
        self,
        caller: ServiceCaller,
        notify_services: tuple[str, ...],
        validation_notify_services: tuple[str, ...] | None = None,
    ) -> None:
        self.caller = caller
        self.notify_services = notify_services
        self.validation_notify_services = validation_notify_services or notify_services

    async def send_cycle_complete(self, event: CompletionEvent) -> None:
        for notify_service in self.notify_services:
            await self._send(notify_service, notification_payload(event))

    async def send_transfer_reminder(
        self,
        *,
        washer_finished_at: datetime,
        buttons: list[dict],
    ) -> None:
        for notify_service in self.notify_services:
            await self._send(
                notify_service,
                transfer_reminder_payload(
                    washer_finished_at=washer_finished_at,
                    snooze_action=buttons[0]["action"],
                    done_action=buttons[1]["action"],
                ),
            )

    async def send_validation_prompt(
        self,
        *,
        event: LifecycleEvent,
        buttons: list[dict],
    ) -> None:
        for notify_service in self.validation_notify_services:
            await self._send(
                notify_service,
                validation_prompt_payload(
                    title=_validation_title(event),
                    yes_action=buttons[0]["action"],
                    no_action=buttons[1]["action"],
                ),
            )

    async def _send(self, notify_service: str, payload: dict) -> None:
        domain, service = notify_service.split(".", 1)
        await self.caller.call_service(domain, service, payload)


def notification_payload(event: CompletionEvent) -> dict:
    runtime = round(event.runtime_minutes)
    return {
        "title": f"{event.appliance_name} finished",
        "message": f"{event.appliance_name} cycle is complete after about {runtime} minutes.",
        "data": {
            "tag": f"laundry-monitor-{event.appliance_slug}-complete",
            "group": "laundry-monitor",
        },
    }


def transfer_reminder_payload(
    *,
    washer_finished_at: datetime,
    snooze_action: str,
    done_action: str,
) -> dict:
    return {
        "title": "Washer load still waiting",
        "message": "Washer finished about 6 hours ago and the dryer has not started.",
        "data": {
            "tag": "laundry-monitor-washer-waiting",
            "group": "laundry-monitor",
            "actions": [
                {"title": "Snooze 2h", "action": snooze_action},
                {"title": "Done", "action": done_action},
            ],
            "washer_finished_at": washer_finished_at.isoformat(),
        },
    }


def validation_prompt_payload(*, title: str, yes_action: str, no_action: str) -> dict:
    return {
        "title": title,
        "message": "Did laundry-monitor detect this correctly?",
        "data": {
            "tag": "laundry-monitor-validation",
            "group": "laundry-monitor",
            "actions": [
                {"title": "Yes", "action": yes_action},
                {"title": "No", "action": no_action},
            ],
        },
    }


def _validation_title(event: LifecycleEvent) -> str:
    verb = "started" if event.event_type.value.endswith("started") else "finished"
    return f"{event.appliance_name} {verb}?"
