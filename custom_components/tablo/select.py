"""Channel picker for live TV."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .api import TabloError
from .coordinator import TabloConfigEntry, TabloCoordinator
from .entity import TabloEntity

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TabloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    try:
        channels = await coordinator.live.async_channels()
    except TabloError as err:
        _LOGGER.warning("Could not load the Tablo channel lineup: %s", err)
        channels = []
    async_add_entities([TabloChannelSelect(coordinator, [c.title for c in channels])])


class TabloChannelSelect(TabloEntity, SelectEntity, RestoreEntity):
    """The channel the watch_channel action plays when none is given."""

    _attr_translation_key = "live_tv_channel"

    def __init__(self, coordinator: TabloCoordinator, options: list[str]) -> None:
        super().__init__(coordinator, "live_tv_channel")
        self._attr_options = options
        self._attr_current_option = options[0] if options else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state in self.options:
            self._attr_current_option = last.state
        self.coordinator.live.selected = self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.coordinator.live.selected = option
        self.async_write_ha_state()
