
# Security

## Trust Boundaries

- App source and generic examples may live in this repo.
- Runtime secrets and host-specific configuration belong outside this repo.
- The container should expose only the configured service port.
- The current inbound HTTP surface is read-only and public: `GET /health`,
  `GET /v1/status`, `GET /docs`, and `GET /openapi.json`.

## Credentials And State

- Home Assistant tokens are secrets and must not be committed.
- Mobile notify service names are runtime configuration and should stay in
  `.env` or `homelab-config` service config.
- Runtime data under `data/` is local state and must not be committed.
- The service reads washer and dryer power state and calls configured notify
  services. It does not switch appliance outlets or perform physical actuation.
- Mobile notification actions only update local workflow state: snooze, mark a
  washer load handled, or record yes/no validation. They do not control
  appliances.
- Validation prompts are disabled by default in production; production washer
  notifications use the configured recipient list.
