"""Media source: browse Tablo channels and play live TV on any media player."""

from __future__ import annotations

from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .api import TabloError
from .const import DOMAIN
from .coordinator import TabloConfigEntry

LIVE = "live"
HLS = "application/vnd.apple.mpegurl"


async def async_get_media_source(hass: HomeAssistant) -> TabloMediaSource:
    """Set up the Tablo media source."""
    return TabloMediaSource(hass)


class TabloMediaSource(MediaSource):
    """Live TV from Tablo DVRs."""

    name = "Tablo"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    def _entries(self) -> list[TabloConfigEntry]:
        return [
            e
            for e in self.hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED
        ]

    def _entry(self, entry_id: str) -> TabloConfigEntry:
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            raise Unresolvable(f"Tablo {entry_id} is not loaded")
        return entry

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        try:
            entry_id, kind, object_id = item.identifier.split("/", 2)
        except ValueError as err:
            raise Unresolvable(f"Unknown Tablo item {item.identifier}") from err
        if kind != LIVE:
            raise Unresolvable(f"Unknown Tablo item {item.identifier}")
        live = self._entry(entry_id).runtime_data.live
        try:
            channel = await live.async_channel(object_id)
            if channel is None:
                raise Unresolvable(f"Channel {object_id} not found")
            url = await live.async_play_url(channel, item.target_media_player)
        except TabloError as err:
            raise Unresolvable(f"Could not start {object_id}: {err}") from err
        return PlayMedia(url, HLS)

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        if item.identifier:
            entry_id = item.identifier.split("/", 1)[0]
            return await self._browse_channels(self._entry(entry_id))

        entries = self._entries()
        if len(entries) == 1:
            return await self._browse_channels(entries[0])
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.CHANNELS,
            title="Tablo",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=[
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=e.entry_id,
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.CHANNELS,
                    title=e.title,
                    can_play=False,
                    can_expand=True,
                )
                for e in entries
            ],
        )

    async def _browse_channels(self, entry: TabloConfigEntry) -> BrowseMediaSource:
        try:
            channels = await entry.runtime_data.live.async_channels()
        except TabloError as err:
            raise Unresolvable(f"Could not load channels: {err}") from err
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=entry.entry_id,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.CHANNELS,
            title=f"{entry.title} Live TV",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.CHANNEL,
            children=[
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"{entry.entry_id}/{LIVE}/{c.object_id}",
                    media_class=MediaClass.CHANNEL,
                    media_content_type=MediaType.CHANNEL,
                    title=c.title,
                    can_play=True,
                    can_expand=False,
                    thumbnail=c.logo,
                )
                for c in channels
            ],
        )
