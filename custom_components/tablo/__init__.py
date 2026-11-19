"""The Tablo DVR integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import TabloLocalClient, TabloWebClient
from .const import CONF_TRANSCODE_URL, DEFAULT_PORT, DOMAIN
from .coordinator import TabloConfigEntry, TabloCoordinator
from .live import LiveTV
from .services import async_setup_services

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.SELECT,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TabloConfigEntry) -> bool:
    """Set up Tablo from a config entry."""
    session = async_get_clientsession(hass)
    client = TabloLocalClient(
        session,
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
    )
    coordinator = TabloCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    transcode_url = entry.options.get(CONF_TRANSCODE_URL)
    web = TabloWebClient(session, transcode_url) if transcode_url else None
    coordinator.live = LiveTV(hass, client, web)
    coordinator.live.async_start_sweeper()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: TabloConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TabloConfigEntry) -> bool:
    """Unload a config entry and stop any live TV it started."""
    await entry.runtime_data.live.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
