from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import LifecycleEvent, LifecycleEventType, Phase, PowerSample


@dataclass
class ApplianceRuntimeState:
    phase: Phase = Phase.IDLE
    candidate_samples: list[PowerSample] = field(default_factory=list)
    cycle_started_at: datetime | None = None
    cycle_completed_at: datetime | None = None
    last_sample_at: datetime | None = None
    last_watts: float | None = None
    last_above_idle_at: datetime | None = None
    quiet_since: datetime | None = None
    peak_watts: float = 0.0
    last_notification_at: datetime | None = None
    last_notification_cycle_completed_at: datetime | None = None
    last_invalid_state: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ApplianceRuntimeState":
        return cls(
            phase=Phase(raw.get("phase", Phase.IDLE)),
            candidate_samples=[
                PowerSample(timestamp=datetime.fromisoformat(item["timestamp"]), watts=float(item["watts"]))
                for item in raw.get("candidate_samples", [])
            ],
            cycle_started_at=_dt(raw.get("cycle_started_at")),
            cycle_completed_at=_dt(raw.get("cycle_completed_at")),
            last_sample_at=_dt(raw.get("last_sample_at")),
            last_watts=_float_or_none(raw.get("last_watts")),
            last_above_idle_at=_dt(raw.get("last_above_idle_at")),
            quiet_since=_dt(raw.get("quiet_since")),
            peak_watts=float(raw.get("peak_watts", 0.0)),
            last_notification_at=_dt(raw.get("last_notification_at")),
            last_notification_cycle_completed_at=_dt(raw.get("last_notification_cycle_completed_at")),
            last_invalid_state=raw.get("last_invalid_state"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = asdict(self)
        payload["phase"] = self.phase.value
        payload["candidate_samples"] = [
            {"timestamp": sample.timestamp.isoformat(), "watts": sample.watts}
            for sample in self.candidate_samples
        ]
        for key in (
            "cycle_started_at",
            "cycle_completed_at",
            "last_sample_at",
            "last_above_idle_at",
            "quiet_since",
            "last_notification_at",
            "last_notification_cycle_completed_at",
        ):
            value = getattr(self, key)
            payload[key] = value.isoformat() if value else None
        return payload

    def status_payload(self, *, stale_after_seconds: int) -> dict[str, Any]:
        entity_fresh = False
        if self.last_sample_at is not None:
            entity_fresh = (
                datetime.now(self.last_sample_at.tzinfo) - self.last_sample_at
            ).total_seconds() <= stale_after_seconds
        return {
            "phase": self.phase.value,
            "last_sample_at": _iso(self.last_sample_at),
            "last_watts": self.last_watts,
            "last_cycle_started_at": _iso(self.cycle_started_at),
            "last_cycle_completed_at": _iso(self.cycle_completed_at),
            "last_notification_at": _iso(self.last_notification_at),
            "entity_fresh": entity_fresh,
            "last_invalid_state": self.last_invalid_state,
            "peak_watts": self.peak_watts,
        }


@dataclass
class WasherTransferState:
    washer_finished_at: datetime | None = None
    waiting_since: datetime | None = None
    next_reminder_at: datetime | None = None
    reminder_sent_at: datetime | None = None
    cleared_at: datetime | None = None
    reminder_token: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WasherTransferState":
        return cls(
            washer_finished_at=_dt(raw.get("washer_finished_at")),
            waiting_since=_dt(raw.get("waiting_since")),
            next_reminder_at=_dt(raw.get("next_reminder_at")),
            reminder_sent_at=_dt(raw.get("reminder_sent_at")),
            cleared_at=_dt(raw.get("cleared_at")),
            reminder_token=raw.get("reminder_token"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "washer_finished_at": _iso(self.washer_finished_at),
            "waiting_since": _iso(self.waiting_since),
            "next_reminder_at": _iso(self.next_reminder_at),
            "reminder_sent_at": _iso(self.reminder_sent_at),
            "cleared_at": _iso(self.cleared_at),
            "reminder_token": self.reminder_token,
        }


@dataclass
class ValidationResponse:
    event_id: str
    response: str
    responded_at: datetime

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ValidationResponse":
        return cls(
            event_id=str(raw["event_id"]),
            response=str(raw["response"]),
            responded_at=datetime.fromisoformat(str(raw["responded_at"])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "response": self.response,
            "responded_at": self.responded_at.isoformat(),
        }


@dataclass
class RuntimeState:
    appliances: dict[str, ApplianceRuntimeState] = field(default_factory=dict)
    lifecycle_events: list[LifecycleEvent] = field(default_factory=list)
    washer_transfer: WasherTransferState = field(default_factory=WasherTransferState)
    validation_responses: dict[str, ValidationResponse] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "RuntimeState":
        state_path = Path(path)
        if not state_path.exists():
            return cls()
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        if "appliances" not in raw:
            return cls(appliances={"washer": ApplianceRuntimeState.from_dict(raw)})
        return cls(
            appliances={
                slug: ApplianceRuntimeState.from_dict(value)
                for slug, value in raw.get("appliances", {}).items()
            },
            lifecycle_events=[
                _lifecycle_event_from_dict(item) for item in raw.get("lifecycle_events", [])
            ],
            washer_transfer=WasherTransferState.from_dict(raw.get("washer_transfer", {})),
            validation_responses={
                event_id: ValidationResponse.from_dict(value)
                for event_id, value in raw.get("validation_responses", {}).items()
            },
        )

    def save(self, path: str | Path) -> None:
        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "appliances": {
                slug: appliance_state.to_dict()
                for slug, appliance_state in self.appliances.items()
            },
            "lifecycle_events": [_lifecycle_event_to_dict(event) for event in self.lifecycle_events],
            "washer_transfer": self.washer_transfer.to_dict(),
            "validation_responses": {
                event_id: response.to_dict()
                for event_id, response in self.validation_responses.items()
            },
        }
        tmp_path = state_path.with_name(f".{state_path.name}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(state_path)


def _lifecycle_event_from_dict(raw: dict[str, Any]) -> LifecycleEvent:
    return LifecycleEvent(
        event_id=str(raw["event_id"]),
        event_type=LifecycleEventType(raw["event_type"]),
        appliance_slug=str(raw["appliance_slug"]),
        appliance_name=str(raw["appliance_name"]),
        occurred_at=datetime.fromisoformat(str(raw["occurred_at"])),
        peak_watts=_float_or_none(raw.get("peak_watts")),
        runtime_minutes=_float_or_none(raw.get("runtime_minutes")),
    )


def _lifecycle_event_to_dict(event: LifecycleEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "appliance_slug": event.appliance_slug,
        "appliance_name": event.appliance_name,
        "occurred_at": event.occurred_at.isoformat(),
        "peak_watts": event.peak_watts,
        "runtime_minutes": event.runtime_minutes,
    }


def _dt(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _float_or_none(value: object) -> float | None:
    return None if value is None else float(value)
