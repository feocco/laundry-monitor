from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Phase(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"


class LifecycleEventType(StrEnum):
    WASHER_STARTED = "washer_started"
    WASHER_FINISHED = "washer_finished"
    DRYER_STARTED = "dryer_started"
    DRYER_FINISHED = "dryer_finished"


@dataclass(frozen=True)
class PowerSample:
    timestamp: datetime
    watts: float


@dataclass(frozen=True)
class CompletionEvent:
    appliance_slug: str
    appliance_name: str
    started_at: datetime
    completed_at: datetime
    peak_watts: float
    runtime_minutes: float


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: str
    event_type: LifecycleEventType
    appliance_slug: str
    appliance_name: str
    occurred_at: datetime
    peak_watts: float | None = None
    runtime_minutes: float | None = None


@dataclass(frozen=True)
class EntityState:
    entity_id: str
    state: str
    last_updated: datetime
