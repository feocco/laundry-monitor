from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .models import LifecycleEventType


@dataclass(frozen=True)
class ApplianceConfig:
    name: str
    power_entity: str
    slug: str
    notify_enabled: bool = True


@dataclass(frozen=True)
class ThresholdConfig:
    idle_watts: float = 5.0
    active_watts: float = 8.0
    start_watts: float = 20.0
    minimum_peak_watts: float = 100.0
    activity_window_minutes: int = 20
    minimum_activity_minutes: int = 10
    minimum_cycle_minutes: int = 20
    quiet_minutes: int = 10
    pause_tolerance_minutes: int = 20
    duplicate_cooldown_minutes: int = 30
    stale_after_minutes: int = 15


@dataclass(frozen=True)
class Settings:
    service_name: str
    host: str
    port: int
    log_level: str
    ha_url: str
    ha_token: str
    appliances: tuple[ApplianceConfig, ...]
    notify_services: tuple[str, ...]
    validation_notify_services: tuple[str, ...]
    lifecycle_validation_enabled: bool
    lifecycle_validation_events: tuple[LifecycleEventType, ...]
    thresholds: ThresholdConfig
    transfer_reminder_hours: int
    transfer_snooze_hours: int
    transfer_repeat_hours: int
    state_path: Path
    dry_run: bool

    @property
    def washer(self) -> ApplianceConfig:
        return self.appliances[0]


def load_settings(env_path: str | None = None) -> Settings:
    load_dotenv(env_path)
    recipients = _csv("NOTIFY_RECIPIENTS", "joe,jess")
    validation_recipients = _csv("LIFECYCLE_VALIDATION_RECIPIENTS", "joe")
    notify_services = tuple(_notify_service_for(recipient) for recipient in recipients)
    validation_notify_services = tuple(
        _notify_service_for(recipient) for recipient in validation_recipients
    )
    return Settings(
        service_name="laundry-monitor",
        host=os.getenv("SERVICE_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVICE_PORT", "8102")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        ha_url=_required("HA_URL").rstrip("/"),
        ha_token=_required("HA_LONG_LIVED_TOKEN"),
        appliances=(
            ApplianceConfig(
                name=os.getenv("WASHER_NAME", "Washer"),
                power_entity=os.getenv(
                    "WASHER_POWER_ENTITY",
                    "sensor.smartthings_outletv4_power",
                ),
                slug="washer",
                notify_enabled=_bool("WASHER_NOTIFY_ENABLED", True),
            ),
            ApplianceConfig(
                name=os.getenv("DRYER_NAME", "Dryer"),
                power_entity=os.getenv("DRYER_POWER_ENTITY", "sensor.dryer_plug_power"),
                slug="dryer",
                notify_enabled=_bool("DRYER_NOTIFY_ENABLED", False),
            ),
        ),
        notify_services=notify_services,
        validation_notify_services=validation_notify_services,
        lifecycle_validation_enabled=_bool("LIFECYCLE_VALIDATION_ENABLED", False),
        lifecycle_validation_events=tuple(
            LifecycleEventType(value)
            for value in _csv(
                "LIFECYCLE_VALIDATION_EVENTS",
                "washer_started,washer_finished,dryer_started,dryer_finished",
            )
        ),
        thresholds=ThresholdConfig(
            idle_watts=_float("IDLE_WATTS", 5.0),
            active_watts=_float("ACTIVE_WATTS", 8.0),
            start_watts=_float("START_WATTS", 20.0),
            minimum_peak_watts=_float("MINIMUM_PEAK_WATTS", 100.0),
            activity_window_minutes=_int("ACTIVITY_WINDOW_MINUTES", 20),
            minimum_activity_minutes=_int("MINIMUM_ACTIVITY_MINUTES", 10),
            minimum_cycle_minutes=_int("MINIMUM_CYCLE_MINUTES", 20),
            quiet_minutes=_int("QUIET_MINUTES", 10),
            pause_tolerance_minutes=_int("PAUSE_TOLERANCE_MINUTES", 20),
            duplicate_cooldown_minutes=_int("DUPLICATE_COOLDOWN_MINUTES", 30),
            stale_after_minutes=_int("STALE_AFTER_MINUTES", 15),
        ),
        transfer_reminder_hours=_int("WASHER_TO_DRYER_REMINDER_HOURS", 6),
        transfer_snooze_hours=_int("WASHER_TO_DRYER_SNOOZE_HOURS", 2),
        transfer_repeat_hours=_int("WASHER_TO_DRYER_REPEAT_HOURS", 8),
        state_path=Path(os.getenv("STATE_PATH", "data/state.json")),
        dry_run=_bool("DRY_RUN", False),
    )


def _notify_service_for(recipient: str) -> str:
    key = f"HA_NOTIFY_{recipient.upper()}_SERVICE"
    service = os.getenv(key)
    if not service:
        raise ValueError(f"Missing required environment variable: {key}")
    if not service.startswith("notify."):
        raise ValueError(f"{key} must look like notify.mobile_app_name")
    return service


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError(f"{name} must contain at least one recipient")
    return values


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}
