"""Sensors for Tablo."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TabloConfigEntry, TabloData
from .entity import TabloEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TabloSensorDescription(SensorEntityDescription):
    """Describes a Tablo sensor."""

    value_fn: Callable[[TabloData], Any]
    attrs_fn: Callable[[TabloData], dict[str, Any]] | None = None


def _next_attrs(data: TabloData) -> dict[str, Any]:
    if not data.scheduled:
        return {}
    a = data.scheduled[0]
    return {
        "title": a.title,
        "episode": a.episode,
        "channel": a.channel,
        "end": a.end.isoformat(),
    }


def _tuner_attrs(data: TabloData) -> dict[str, Any]:
    return {
        "tuners": data.tuner_count,
        "recording": len(data.tuners_recording),
    }


SENSORS: tuple[TabloSensorDescription, ...] = (
    TabloSensorDescription(
        key="tuners_in_use",
        translation_key="tuners_in_use",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.tuners_in_use,
        attrs_fn=_tuner_attrs,
    ),
    TabloSensorDescription(
        key="recordings",
        translation_key="recordings",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.recording_count,
    ),
    TabloSensorDescription(
        key="scheduled_recordings",
        translation_key="scheduled_recordings",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.scheduled),
    ),
    TabloSensorDescription(
        key="next_recording",
        translation_key="next_recording",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.scheduled[0].start if d.scheduled else None,
        attrs_fn=_next_attrs,
    ),
    TabloSensorDescription(
        key="storage_free",
        translation_key="storage_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        suggested_display_precision=1,
        value_fn=lambda d: d.storage_free,
    ),
    TabloSensorDescription(
        key="storage_used_percent",
        translation_key="storage_used_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: (
            round(100 * d.storage_used / d.storage_size, 1) if d.storage_size else None
        ),
    ),
    TabloSensorDescription(
        key="storage_size",
        translation_key="storage_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.storage_size,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TabloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(TabloSensor(coordinator, d) for d in SENSORS)


class TabloSensor(TabloEntity, SensorEntity):
    """A Tablo sensor."""

    entity_description: TabloSensorDescription

    def __init__(self, coordinator, description: TabloSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if fn := self.entity_description.attrs_fn:
            return fn(self.coordinator.data)
        return None
