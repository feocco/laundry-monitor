from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homelab import NotificationActionRouter

from .config import Settings
from .detector import CycleDetector
from .ha import HomeAssistantClient
from .models import CompletionEvent, EntityState, LifecycleEvent, LifecycleEventType, PowerSample
from .notify import Notifier
from .runtime_state import ApplianceRuntimeState, RuntimeState, ValidationResponse
from .web import StatusServer


LOGGER = logging.getLogger(__name__)
TRANSFER_SNOOZE_PREFIX = "LAUNDRY_TRANSFER_SNOOZE"
TRANSFER_DONE_PREFIX = "LAUNDRY_TRANSFER_DONE"
VALIDATE_YES_PREFIX = "LAUNDRY_VALIDATE_YES"
VALIDATE_NO_PREFIX = "LAUNDRY_VALIDATE_NO"


class LaundryMonitor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state = RuntimeState.load(settings.state_path)
        self.detectors: dict[str, CycleDetector] = {}
        self.entity_to_slug: dict[str, str] = {}
        for appliance in settings.appliances:
            appliance_state = self.state.appliances.setdefault(
                appliance.slug,
                ApplianceRuntimeState(),
            )
            self.detectors[appliance.slug] = CycleDetector(
                appliance,
                settings.thresholds,
                appliance_state,
            )
            self.entity_to_slug[appliance.power_entity] = appliance.slug
        self.appliances_by_slug = {appliance.slug: appliance for appliance in settings.appliances}
        self.ha = HomeAssistantClient(settings)
        self.notifier = Notifier(
            self.ha,
            settings.notify_services,
            settings.validation_notify_services,
        )
        self.action_router = NotificationActionRouter()
        self.action_router.register(TRANSFER_SNOOZE_PREFIX, self._handle_transfer_snooze)
        self.action_router.register(TRANSFER_DONE_PREFIX, self._handle_transfer_done)
        self.action_router.register(VALIDATE_YES_PREFIX, self._handle_validation_yes)
        self.action_router.register(VALIDATE_NO_PREFIX, self._handle_validation_no)
        stale_after_seconds = settings.thresholds.stale_after_minutes * 60
        self.web = StatusServer(
            settings.host,
            settings.port,
            lambda: self.status_payload(stale_after_seconds=stale_after_seconds),
        )
        self._action_now: datetime | None = None

    async def run(self) -> None:
        self.web.start()
        LOGGER.info("Started health server on %s:%s", self.settings.host, self.settings.port)
        try:
            self.ha.add_event_handler(self.handle_event)
            while True:
                try:
                    await self._run_connection()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception("Home Assistant monitor connection failed")
                await self.ha.close()
                await asyncio.sleep(30)
        finally:
            self.web.stop()
            await self.ha.close()

    async def _run_connection(self) -> None:
        await self.ha.connect()
        await self.reconcile_current_state()
        await self.ha.subscribe_state_changed()
        await self.ha.subscribe_notification_actions()
        LOGGER.info("Monitoring %s", ", ".join(self.entity_to_slug))
        reconcile_task = asyncio.create_task(self._periodic_reconcile())
        try:
            await self.ha.wait_closed()
        finally:
            reconcile_task.cancel()
            try:
                await reconcile_task
            except asyncio.CancelledError:
                pass

    async def reconcile_current_state(self) -> None:
        now = datetime.now().astimezone()
        for appliance in self.settings.appliances:
            current = await self.ha.get_entity_state(appliance.power_entity)
            if current is not None:
                await self.observe_entity_state(current)
                continue
            self.detectors[appliance.slug].observe_invalid("missing_entity")
            LOGGER.error("%s entity not found: %s", appliance.name, appliance.power_entity)
        await self.check_scheduled_workflows(now)
        self.state.save(self.settings.state_path)

    async def _periodic_reconcile(self) -> None:
        while True:
            await asyncio.sleep(300)
            await self.reconcile_current_state()

    async def handle_event(self, event: dict[str, Any]) -> None:
        if event.get("event_type") == "mobile_app_notification_action":
            self.handle_notification_action(event)
            self.state.save(self.settings.state_path)
            return
        data = event.get("data") or {}
        if data.get("entity_id") not in self.entity_to_slug:
            return
        new_state = data.get("new_state")
        if isinstance(new_state, dict):
            await self.observe_entity_state(
                EntityState(
                    entity_id=str(new_state.get("entity_id")),
                    state=str(new_state.get("state")),
                    last_updated=_parse_event_time(new_state.get("last_updated")),
                )
            )

    async def observe_entity_state(self, entity_state: EntityState) -> None:
        slug = self.entity_to_slug.get(entity_state.entity_id)
        if slug is None:
            return
        detector = self.detectors[slug]
        sample = _sample_from_state(entity_state)
        if sample is None:
            detector.observe_invalid(entity_state.state)
            self.state.save(self.settings.state_path)
            return
        if slug == "dryer" and sample.watts >= self.settings.thresholds.start_watts:
            self._clear_washer_waiting(sample.timestamp)
        completion = detector.observe(sample)
        for lifecycle_event in detector.drain_lifecycle_events():
            await self._handle_lifecycle_event(lifecycle_event)
        if completion is not None:
            await self._handle_completion(completion)
        await self.check_scheduled_workflows(sample.timestamp)
        self.state.save(self.settings.state_path)

    async def _handle_lifecycle_event(self, event: LifecycleEvent) -> None:
        if not any(existing.event_id == event.event_id for existing in self.state.lifecycle_events):
            self.state.lifecycle_events.append(event)
        if event.event_type is LifecycleEventType.WASHER_FINISHED:
            self._mark_washer_waiting(event)
        elif event.event_type is LifecycleEventType.DRYER_STARTED:
            self._clear_washer_waiting(event.occurred_at)
        if (
            self.settings.lifecycle_validation_enabled
            and event.event_type in self.settings.lifecycle_validation_events
            and event.event_id not in self.state.validation_responses
        ):
            await self.notifier.send_validation_prompt(
                event=event,
                buttons=[
                    {
                        "title": "Yes",
                        "action": NotificationActionRouter.make_action(
                            VALIDATE_YES_PREFIX,
                            event.event_id,
                        ),
                    },
                    {
                        "title": "No",
                        "action": NotificationActionRouter.make_action(
                            VALIDATE_NO_PREFIX,
                            event.event_id,
                        ),
                    },
                ],
            )

    async def _handle_completion(self, event: CompletionEvent) -> None:
        appliance = self.appliances_by_slug[event.appliance_slug]
        detector = self.detectors[event.appliance_slug]
        if appliance.notify_enabled and detector.should_notify(event):
            await self.notifier.send_cycle_complete(event)
            detector.mark_notified(event)
            LOGGER.info(
                "Sent %s completion notification for cycle ending %s",
                event.appliance_name,
                event.completed_at.isoformat(),
            )

    async def check_scheduled_workflows(self, now: datetime) -> None:
        transfer = self.state.washer_transfer
        if (
            transfer.waiting_since is None
            or transfer.next_reminder_at is None
            or now < transfer.next_reminder_at
        ):
            return
        token = transfer.reminder_token or _token("washer-transfer", transfer.waiting_since)
        transfer.reminder_token = token
        await self.notifier.send_transfer_reminder(
            washer_finished_at=transfer.washer_finished_at or transfer.waiting_since,
            buttons=[
                {
                    "title": "Snooze 2h",
                    "action": NotificationActionRouter.make_action(
                        TRANSFER_SNOOZE_PREFIX,
                        token,
                    ),
                },
                {
                    "title": "Done",
                    "action": NotificationActionRouter.make_action(
                        TRANSFER_DONE_PREFIX,
                        token,
                    ),
                },
            ],
        )
        transfer.reminder_sent_at = now
        transfer.next_reminder_at = now + timedelta(hours=self.settings.transfer_repeat_hours)

    def handle_notification_action(
        self,
        event: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> bool:
        self._action_now = now or datetime.now().astimezone()
        try:
            return self.action_router.handle_event(event)
        finally:
            self._action_now = None

    def status_payload(self, *, stale_after_seconds: int) -> dict[str, Any]:
        appliances = {}
        status = "ok"
        for appliance in self.settings.appliances:
            appliance_state = self.state.appliances[appliance.slug]
            payload = appliance_state.status_payload(stale_after_seconds=stale_after_seconds)
            payload["entity_id"] = appliance.power_entity
            payload["name"] = appliance.name
            appliances[appliance.slug] = payload
            if appliance_state.last_invalid_state is not None:
                status = "degraded"
        return {
            "service": self.settings.service_name,
            "status": status,
            "dry_run": self.settings.dry_run,
            "appliances": appliances,
            "washer_transfer": {
                "waiting": self.state.washer_transfer.waiting_since is not None,
                "washer_finished_at": _iso(self.state.washer_transfer.washer_finished_at),
                "waiting_since": _iso(self.state.washer_transfer.waiting_since),
                "next_reminder_at": _iso(self.state.washer_transfer.next_reminder_at),
                "reminder_sent_at": _iso(self.state.washer_transfer.reminder_sent_at),
                "cleared_at": _iso(self.state.washer_transfer.cleared_at),
            },
            "validation": {
                "pending": self._pending_validation_events(),
                "latest_response": _latest_validation_response(self.state.validation_responses),
            },
            "lifecycle": self._lifecycle_summary(),
        }

    def _pending_validation_events(self) -> list[str]:
        if not self.settings.lifecycle_validation_enabled:
            return []
        return [
            event.event_id
            for event in self.state.lifecycle_events
            if event.event_type in self.settings.lifecycle_validation_events
            and event.event_id not in self.state.validation_responses
        ]

    def _lifecycle_summary(self) -> dict[str, Any]:
        appliances: dict[str, dict[str, Any]] = {
            appliance.slug: {
                "starts": 0,
                "finishes": 0,
                "last_started_at": None,
                "last_finished_at": None,
                "runtime_minutes_range": None,
                "peak_watts_range": None,
            }
            for appliance in self.settings.appliances
        }
        runtimes: dict[str, list[float]] = {
            appliance.slug: [] for appliance in self.settings.appliances
        }
        peaks: dict[str, list[float]] = {
            appliance.slug: [] for appliance in self.settings.appliances
        }

        for event in self.state.lifecycle_events:
            appliance = appliances.setdefault(
                event.appliance_slug,
                {
                    "starts": 0,
                    "finishes": 0,
                    "last_started_at": None,
                    "last_finished_at": None,
                    "runtime_minutes_range": None,
                    "peak_watts_range": None,
                },
            )
            if event.event_type in {
                LifecycleEventType.WASHER_STARTED,
                LifecycleEventType.DRYER_STARTED,
            }:
                appliance["starts"] += 1
                appliance["last_started_at"] = _iso(event.occurred_at)
                continue
            appliance["finishes"] += 1
            appliance["last_finished_at"] = _iso(event.occurred_at)
            if event.runtime_minutes is not None:
                runtimes.setdefault(event.appliance_slug, []).append(event.runtime_minutes)
            if event.peak_watts is not None:
                peaks.setdefault(event.appliance_slug, []).append(event.peak_watts)

        for slug, values in runtimes.items():
            if values:
                appliances[slug]["runtime_minutes_range"] = [min(values), max(values)]
        for slug, values in peaks.items():
            if values:
                appliances[slug]["peak_watts_range"] = [min(values), max(values)]

        return {
            "appliances": appliances,
            "latest_events": [
                _lifecycle_event_status(event, self.state.validation_responses)
                for event in sorted(
                    self.state.lifecycle_events,
                    key=lambda item: item.occurred_at,
                    reverse=True,
                )[:12]
            ],
        }

    def _mark_washer_waiting(self, event: LifecycleEvent) -> None:
        transfer = self.state.washer_transfer
        transfer.washer_finished_at = event.occurred_at
        transfer.waiting_since = event.occurred_at
        transfer.next_reminder_at = event.occurred_at + timedelta(
            hours=self.settings.transfer_reminder_hours
        )
        transfer.reminder_sent_at = None
        transfer.cleared_at = None
        transfer.reminder_token = _token("washer-transfer", event.occurred_at)

    def _clear_washer_waiting(self, cleared_at: datetime) -> None:
        transfer = self.state.washer_transfer
        if transfer.waiting_since is None:
            return
        transfer.waiting_since = None
        transfer.next_reminder_at = None
        transfer.cleared_at = cleared_at

    def _handle_transfer_snooze(self, token: str, event: dict[str, Any]) -> None:
        transfer = self.state.washer_transfer
        if token != transfer.reminder_token or transfer.waiting_since is None:
            return
        now = self._action_now or datetime.now().astimezone()
        transfer.next_reminder_at = now + timedelta(hours=self.settings.transfer_snooze_hours)

    def _handle_transfer_done(self, token: str, event: dict[str, Any]) -> None:
        if token != self.state.washer_transfer.reminder_token:
            return
        self._clear_washer_waiting(self._action_now or datetime.now().astimezone())

    def _handle_validation_yes(self, event_id: str, event: dict[str, Any]) -> None:
        self._record_validation(event_id, "yes")

    def _handle_validation_no(self, event_id: str, event: dict[str, Any]) -> None:
        self._record_validation(event_id, "no")

    def _record_validation(self, event_id: str, response: str) -> None:
        if not any(event.event_id == event_id for event in self.state.lifecycle_events):
            return
        self.state.validation_responses[event_id] = ValidationResponse(
            event_id=event_id,
            response=response,
            responded_at=self._action_now or datetime.now().astimezone(),
        )


def _sample_from_state(entity_state: EntityState) -> PowerSample | None:
    try:
        watts = float(entity_state.state)
    except ValueError:
        return None
    return PowerSample(timestamp=entity_state.last_updated, watts=watts)


def _parse_event_time(value: str | None) -> datetime:
    if not value:
        return datetime.now().astimezone()
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _token(prefix: str, timestamp: datetime) -> str:
    return f"{prefix}-{timestamp.isoformat()}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _latest_validation_response(responses: dict[str, ValidationResponse]) -> dict | None:
    if not responses:
        return None
    latest = max(responses.values(), key=lambda response: response.responded_at)
    return latest.to_dict()


def _lifecycle_event_status(
    event: LifecycleEvent,
    responses: dict[str, ValidationResponse],
) -> dict[str, Any]:
    response = responses.get(event.event_id)
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "appliance": event.appliance_slug,
        "occurred_at": event.occurred_at.isoformat(),
        "runtime_minutes": event.runtime_minutes,
        "peak_watts": event.peak_watts,
        "validation_response": response.response if response else None,
    }


def run_monitor(settings: Settings) -> None:
    asyncio.run(LaundryMonitor(settings).run())
