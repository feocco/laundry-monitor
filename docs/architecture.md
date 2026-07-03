
# Architecture

`laundry-monitor` is a small Python Docker service that turns washer and dryer
power readings into lifecycle events and actionable mobile notifications.

## Boundaries

- Source, tests, Dockerfile, and GHCR publishing live in this app repo.
- Runtime configuration, secrets, Compose files, and host placement live in
  `homelab-config`.
- `homelab.yaml` documents the app-side deploy contract used by agents and
  deploy planning tools.

## Flow

1. The service starts a small HTTP server that serves health, detailed status,
   browser-friendly service docs, and an OpenAPI document.
2. It connects to Home Assistant over WebSocket through
   `homelab.HomeAssistantWebSocketClient`.
3. It loads current washer and dryer power state, then subscribes to
   `state_changed` events for both configured power sensors.
4. Each appliance detector records internal start/finish lifecycle events in
   `data/state.json`.
5. Washer finish starts a transfer workflow. Dryer start clears it. If no dryer
   start occurs within the configured reminder window, the service sends Joe and
   Jess a reminder with `Snooze 2h` and `Done` actions. The reminder repeats on
   the configured interval until it is cleared.
6. The service also subscribes to `mobile_app_notification_action` and routes
   reminder and validation buttons through `homelab.NotificationActionRouter`.

## Validation

Lifecycle validation is a rollout aid and is disabled in normal production use.
When enabled, Joe receives yes/no prompts for selected start and finish events.
Responses are persisted for review and exposed through `GET /v1/status`, but
they do not alter detector state.
