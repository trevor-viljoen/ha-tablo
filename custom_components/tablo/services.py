"""Actions for Tablo live TV."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .api import TabloError
from .const import (
    ATTR_CHANNEL,
    ATTR_CONFIG_ENTRY_ID,
    DOMAIN,
    SERVICE_WATCH_CHANNEL,
    UNSUPPORTED_PLAYER_MESSAGE,
    UNSUPPORTED_PLAYER_PLATFORMS,
)
from .coordinator import TabloConfigEntry

WATCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional(ATTR_CHANNEL): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


def _entry(hass: HomeAssistant, entry_id: str | None) -> TabloConfigEntry:
    loaded = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED and (entry_id is None or e.entry_id == entry_id)
    ]
    if not loaded:
        raise ServiceValidationError("No loaded Tablo matches that config entry")
    if len(loaded) > 1:
        raise ServiceValidationError("Several Tablos are set up; pass config_entry_id")
    return loaded[0]


async def _async_watch(call: ServiceCall) -> None:
    registry = er.async_get(call.hass)
    for player in call.data[ATTR_ENTITY_ID]:
        reg = registry.async_get(player)
        if reg and reg.platform in UNSUPPORTED_PLAYER_PLATFORMS:
            raise ServiceValidationError(f"{player}: {UNSUPPORTED_PLAYER_MESSAGE}")
    live = _entry(call.hass, call.data.get(ATTR_CONFIG_ENTRY_ID)).runtime_data.live
    query = call.data.get(ATTR_CHANNEL) or live.selected
    if not query:
        raise ServiceValidationError("No channel given and none selected")
    try:
        channel = await live.async_find_channel(query)
    except TabloError as err:
        raise HomeAssistantError(f"Could not load channels: {err}") from err
    if channel is None:
        raise ServiceValidationError(f"No channel matches {query!r}")
    for player in call.data[ATTR_ENTITY_ID]:
        try:
            await live.async_watch(channel, player)
        except TabloError as err:
            raise HomeAssistantError(f"Could not start {channel.title}: {err}") from err


def async_setup_services(hass: HomeAssistant) -> None:
    hass.services.async_register(DOMAIN, SERVICE_WATCH_CHANNEL, _async_watch, WATCH_SCHEMA)
