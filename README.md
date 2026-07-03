
# laundry-monitor

Home Assistant laundry lifecycle monitor with mobile notifications.

`laundry-monitor` watches washer and dryer power sensors, records lifecycle
events, and sends actionable mobile notifications. Its main workflow is a
washer-to-dryer reminder: when the washer finishes and the dryer has not started
within 6 hours, Joe and Jess get a reminder with `Snooze 2h` and `Done`
actions. The reminder repeats every 8 hours until the dryer starts or the load
is marked done.

## Quickstart

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m laundry_monitor.main
```

Copy `.env.example` to `.env` for local testing and fill in the Home Assistant
token and mobile notify service names. The service exposes `GET /health` and
`GET /v1/status` on port `8102` by default.

Persistent runtime state lives under `data/`.

## Detection

The default detector is intentionally conservative for both appliances:

- running starts after sustained activity above 8 W with a start signal above
  20 W;
- a cycle must run at least 20 minutes and peak above 100 W;
- completion requires low power under 5 W for 10 minutes. Washer detection also
  keeps the existing 20-minute pause tolerance to avoid false completion during
  long pauses.

Washer completions notify the configured recipients immediately. Dryer
completion notifications are disabled by default, but dryer starts still clear
the washer-to-dryer waiting state. `GET /v1/status` includes recent lifecycle
counts and events for production review.

## Validation

Lifecycle validation prompts are disabled by default. During a future rollout,
they can be enabled so Joe receives yes/no prompts for detected washer/dryer
starts and finishes. These responses are stored in `data/state.json` and shown
in `GET /v1/status`; they do not mutate detector state.

## Deployment

This repo publishes `ghcr.io/feocco/laundry-monitor:latest` from
`.github/workflows/container.yml`. Runtime deployment is owned by
`homelab-config`; this repo's deploy contract is `homelab.yaml`.
