"""Calendar of scheduled Tablo recordings."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import TabloAiring, TabloConfigEntry
from .entity import TabloEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TabloConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([TabloScheduleCalendar(entry.runtime_data)])


def _event(a: TabloAiring) -> CalendarEvent:
    summary = f"{a.title}: {a.episode}" if a.episode else a.title
    return CalendarEvent(
        start=a.start,
        end=a.end,
        summary=summary,
        description=a.description,
        location=a.channel,
        uid=a.path,
    )


class TabloScheduleCalendar(TabloEntity, CalendarEntity):
    """Upcoming scheduled recordings."""

    _attr_translation_key = "scheduled_recordings"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "schedule")

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.utcnow()
        for a in self.coordinator.data.scheduled:
            if a.end > now:
                return _event(a)
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            _event(a)
            for a in self.coordinator.data.scheduled
            if a.end > start_date and a.start < end_date
        ]
