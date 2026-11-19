"""The Tablo DVR integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TabloLocalClient
from .const import DEFAULT_PORT
from .coordinator import TabloConfigEntry, TabloCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: TabloConfigEntry) -> bool:
    """Set up Tablo from a config entry."""
    client = TabloLocalClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
    )
    coordinator = TabloCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TabloConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
