"""Binary sensors for Tablo."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    async_add_entities([TabloRecordingSensor(entry.runtime_data)])


class TabloRecordingSensor(TabloEntity, BinarySensorEntity):
    """On while any tuner is recording."""

    _attr_translation_key = "recording"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "recording")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.tuners_recording)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "tuners": [
                {"channel": t.get("channel"), "recording": t.get("recording")}
                for t in self.coordinator.data.tuners_recording
            ]
        }
