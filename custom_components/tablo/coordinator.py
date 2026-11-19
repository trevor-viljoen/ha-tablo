"""Data update coordinator for Tablo."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TabloError, TabloLocalClient
from .const import DOMAIN, MAX_SCHEDULED, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type TabloConfigEntry = ConfigEntry[TabloCoordinator]


@dataclass(slots=True)
class TabloAiring:
    """A scheduled airing."""

    path: str
    title: str
    episode: str | None
    description: str | None
    channel: str | None
    start: datetime
    end: datetime


@dataclass(slots=True)
class TabloData:
    """Snapshot of device state."""

    info: dict[str, Any]
    tuners: list[dict[str, Any]]
    drives: list[dict[str, Any]]
    recording_count: int
    scheduled: list[TabloAiring] = field(default_factory=list)

    @property
    def tuners_in_use(self) -> int:
        return sum(1 for t in self.tuners if t.get("in_use"))

    @property
    def tuners_recording(self) -> list[dict[str, Any]]:
        return [t for t in self.tuners if t.get("recording")]

    @property
    def tuner_count(self) -> int:
        model = self.info.get("model") or {}
        return int(model.get("tuners") or len(self.tuners))

    def _drive_sum(self, key: str) -> int:
        return sum(int(d.get(key) or 0) for d in self.drives if d.get("connected"))

    @property
    def storage_size(self) -> int:
        return self._drive_sum("size")

    @property
    def storage_free(self) -> int:
        return self._drive_sum("free")

    @property
    def storage_used(self) -> int:
        return self._drive_sum("usage")


def _channel_name(airing: dict[str, Any]) -> str | None:
    ch = ((airing.get("airing_details") or {}).get("channel") or {}).get("channel")
    if not ch:
        return None
    sign = ch.get("call_sign") or ch.get("name") or ""
    if ch.get("major"):
        return f"{ch['major']}.{ch.get('minor', 0)} {sign}".strip()
    return sign or None


def _parse_airing(path: str, obj: dict[str, Any]) -> TabloAiring | None:
    details = obj.get("airing_details") or {}
    raw = details.get("datetime")
    if not raw:
        return None
    try:
        start = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    duration = int(details.get("duration") or 0)
    episode = obj.get("episode") or {}
    movie = obj.get("movie_airing") or {}
    title = details.get("show_title") or movie.get("title") or "Recording"
    return TabloAiring(
        path=path,
        title=title,
        episode=episode.get("title"),
        description=episode.get("description") or movie.get("description"),
        channel=_channel_name(obj),
        start=start,
        end=start + timedelta(seconds=duration),
    )


class TabloCoordinator(DataUpdateCoordinator[TabloData]):
    """Polls the Tablo for tuner, storage, recording and schedule state."""

    config_entry: TabloConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: TabloConfigEntry, client: TabloLocalClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> TabloData:
        try:
            info = await self.client.server_info()
            tuners = await self.client.tuners()
            drives = await self.client.harddrives()
            recordings = await self.client.recording_paths()
            scheduled_paths = await self.client.scheduled_paths()
            details = (
                await self.client.batch(scheduled_paths[:MAX_SCHEDULED]) if scheduled_paths else {}
            )
        except TabloError as err:
            raise UpdateFailed(str(err)) from err

        scheduled = [
            a
            for p, obj in details.items()
            if isinstance(obj, dict) and (a := _parse_airing(p, obj))
        ]
        scheduled.sort(key=lambda a: a.start)
        return TabloData(
            info=info,
            tuners=tuners,
            drives=drives,
            recording_count=len(recordings),
            scheduled=scheduled,
        )
