"""Button to stop all live TV streams started by Home Assistant."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TabloConfigEntry
from .entity import TabloEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TabloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([TabloStopLiveButton(entry.runtime_data)])


class TabloStopLiveButton(TabloEntity, ButtonEntity):
    """Stops every live TV stream and frees the tuners."""

    _attr_translation_key = "stop_live_tv"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "stop_live_tv")

    async def async_press(self) -> None:
        await self.coordinator.live.async_stop_all()
