
# Configuration

Use `.env.example` for placeholders only. Real values belong in ignored local
`.env` files or private `homelab-config` runtime config.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SERVICE_HOST` | `0.0.0.0` | HTTP bind host inside the container. |
| `SERVICE_PORT` | `8102` | HTTP bind port inside the container. |
| `LOG_LEVEL` | `INFO` | Python logging verbosity. |
| `HA_URL` | required | Home Assistant base URL. |
| `HA_LONG_LIVED_TOKEN` | required | Home Assistant long-lived access token. |
| `HA_NOTIFY_JOE_SERVICE` | required | Joe mobile app notify service, e.g. `notify.mobile_app_joes_iphone`. |
| `HA_NOTIFY_JESS_SERVICE` | required | Jess mobile app notify service. |
| `NOTIFY_RECIPIENTS` | `joe,jess` | Recipients to notify. Each recipient needs a matching `HA_NOTIFY_<NAME>_SERVICE`. |
| `WASHER_NAME` | `Washer` | Display name used in notifications. |
| `WASHER_POWER_ENTITY` | `sensor.smartthings_outletv4_power` | Home Assistant power sensor used for washer detection. |
| `WASHER_NOTIFY_ENABLED` | `true` | Enables washer completion notifications. |
| `DRYER_NAME` | `Dryer` | Display name used for dryer lifecycle events. |
| `DRYER_POWER_ENTITY` | `sensor.dryer_plug_power` | Home Assistant power sensor used for dryer detection and transfer clearing. |
| `DRYER_NOTIFY_ENABLED` | `false` | Enables dryer completion notifications after validation. |
| `WASHER_TO_DRYER_REMINDER_HOURS` | `6` | Hours after washer completion before sending the not-moved reminder. |
| `WASHER_TO_DRYER_SNOOZE_HOURS` | `2` | Snooze duration for the washer-not-moved reminder action. |
| `WASHER_TO_DRYER_REPEAT_HOURS` | `8` | Repeat interval for washer-not-moved reminders until cleared or dryer start. |
| `LIFECYCLE_VALIDATION_ENABLED` | `false` | Sends Joe yes/no prompts for configured lifecycle events during rollout. |
| `LIFECYCLE_VALIDATION_RECIPIENTS` | `joe` | Recipients for lifecycle validation prompts. |
| `LIFECYCLE_VALIDATION_EVENTS` | all start/finish events | Comma-separated lifecycle events to validate. |
| `STATE_PATH` | `data/state.json` | Persistent detector state file. |
| `IDLE_WATTS` | `5` | Power below this is treated as idle/quiet. |
| `ACTIVE_WATTS` | `8` | Power above this contributes to start detection. |
| `START_WATTS` | `20` | Minimum peak during the start window. |
| `MINIMUM_PEAK_WATTS` | `100` | Minimum cycle peak needed before completion can notify. |
| `ACTIVITY_WINDOW_MINUTES` | `20` | Rolling start-detection window. |
| `MINIMUM_ACTIVITY_MINUTES` | `10` | Required active span inside the start window. |
| `MINIMUM_CYCLE_MINUTES` | `20` | Minimum valid cycle runtime. |
| `QUIET_MINUTES` | `10` | Required low-power quiet period before completion is considered. |
| `PAUSE_TOLERANCE_MINUTES` | `20` | Low-power pauses shorter than this do not complete a cycle. |
| `DUPLICATE_COOLDOWN_MINUTES` | `30` | Suppresses duplicate notifications for the same cycle. |
| `STALE_AFTER_MINUTES` | `15` | Health status degrades when no fresh numeric sample has arrived. |
| `DRY_RUN` | `false` | Skips Home Assistant service calls when true. |
