from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

from homelab import HomeAssistantConfig, HomeAssistantWebSocketClient

from .config import Settings
from .models import EntityState


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]
LOGGER = logging.getLogger(__name__)


class HomeAssistantClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._handlers: list[EventHandler] = []
        self._client = self._new_client()

    async def connect(self) -> None:
        await self._client.connect()

    async def close(self) -> None:
        try:
            await self._client.close()
        finally:
            self._client = self._new_client()

    async def wait_closed(self) -> None:
        await self._client.wait_closed()

    def add_event_handler(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def get_entity_state(self, entity_id: str) -> EntityState | None:
        states = await self._client.get_states()
        for state in states:
            if state.get("entity_id") == entity_id:
                return parse_entity_state(state)
        return None

    async def subscribe_state_changed(self) -> None:
        await self._client.subscribe_events("state_changed")

    async def subscribe_notification_actions(self) -> None:
        await self._client.subscribe_events("mobile_app_notification_action")

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any],
    ) -> dict[str, Any]:
        if self.settings.dry_run:
            return {"dry_run": True, "domain": domain, "service": service}
        return await self._client.call_service(domain, service, service_data)

    async def _dispatch_event(self, event: dict[str, Any]) -> None:
        for handler in list(self._handlers):
            try:
                await handler(event)
            except Exception:
                LOGGER.exception("Home Assistant event handler failed")

    def _new_client(self) -> HomeAssistantWebSocketClient:
        client = HomeAssistantWebSocketClient(
            HomeAssistantConfig(
                ha_url=self.settings.ha_url,
                ha_long_lived_token=self.settings.ha_token,
            )
        )
        client.add_event_handler(self._dispatch_event)
        return client


def parse_entity_state(raw: dict[str, Any]) -> EntityState:
    return EntityState(
        entity_id=raw["entity_id"],
        state=str(raw.get("state", "")),
        last_updated=_parse_datetime(raw.get("last_updated")),
    )


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now().astimezone()
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
