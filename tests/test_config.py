from __future__ import annotations

import pytest

from laundry_monitor.models import LifecycleEventType
from laundry_monitor.config import load_settings


def test_load_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HA_URL", "https://ha.example/")
    monkeypatch.setenv("HA_LONG_LIVED_TOKEN", "token")
    monkeypatch.setenv("HA_NOTIFY_JOE_SERVICE", "notify.mobile_app_joe")
    monkeypatch.setenv("HA_NOTIFY_JESS_SERVICE", "notify.mobile_app_jess")

    settings = load_settings()

    assert settings.ha_url == "https://ha.example"
    assert settings.appliances[0].power_entity == "sensor.smartthings_outletv4_power"
    assert settings.appliances[0].name == "Washer"
    assert settings.appliances[0].slug == "washer"
    assert settings.appliances[0].notify_enabled is True
    assert settings.appliances[1].power_entity == "sensor.dryer_plug_power"
    assert settings.appliances[1].name == "Dryer"
    assert settings.appliances[1].slug == "dryer"
    assert settings.appliances[1].notify_enabled is False
    assert settings.notify_services == (
        "notify.mobile_app_joe",
        "notify.mobile_app_jess",
    )
    assert settings.validation_notify_services == ("notify.mobile_app_joe",)
    assert settings.lifecycle_validation_enabled is False
    assert settings.lifecycle_validation_events == (
        LifecycleEventType.WASHER_STARTED,
        LifecycleEventType.WASHER_FINISHED,
        LifecycleEventType.DRYER_STARTED,
        LifecycleEventType.DRYER_FINISHED,
    )
    assert settings.transfer_reminder_hours == 6
    assert settings.transfer_snooze_hours == 2
    assert settings.transfer_repeat_hours == 8
    assert settings.thresholds.idle_watts == 5.0


def test_load_settings_overrides_repeat_reminder_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HA_URL", "https://ha.example/")
    monkeypatch.setenv("HA_LONG_LIVED_TOKEN", "token")
    monkeypatch.setenv("HA_NOTIFY_JOE_SERVICE", "notify.mobile_app_joe")
    monkeypatch.setenv("HA_NOTIFY_JESS_SERVICE", "notify.mobile_app_jess")
    monkeypatch.setenv("WASHER_TO_DRYER_REPEAT_HOURS", "12")

    settings = load_settings()

    assert settings.transfer_repeat_hours == 12


def test_load_settings_requires_home_assistant_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HA_URL", raising=False)
    monkeypatch.setenv("HA_LONG_LIVED_TOKEN", "token")
    monkeypatch.setenv("HA_NOTIFY_JOE_SERVICE", "notify.mobile_app_joe")
    monkeypatch.setenv("HA_NOTIFY_JESS_SERVICE", "notify.mobile_app_jess")

    with pytest.raises(ValueError, match="HA_URL"):
        load_settings()


def test_load_settings_requires_notify_service_for_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HA_URL", "https://ha.example")
    monkeypatch.setenv("HA_LONG_LIVED_TOKEN", "token")
    monkeypatch.setenv("NOTIFY_RECIPIENTS", "joe,jess")
    monkeypatch.setenv("HA_NOTIFY_JOE_SERVICE", "notify.mobile_app_joe")
    monkeypatch.delenv("HA_NOTIFY_JESS_SERVICE", raising=False)

    with pytest.raises(ValueError, match="HA_NOTIFY_JESS_SERVICE"):
        load_settings()
