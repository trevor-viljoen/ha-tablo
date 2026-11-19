"""Live TV: channel lineup and stream session lifecycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from functools import partial

from homeassistant.const import (
    STATE_IDLE,
    STATE_OFF,
    STATE_PAUSED,
    STATE_STANDBY,
    STATE_UNAVAILABLE,
)
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .api import TabloChannel, TabloError, TabloLocalClient, TabloWebClient
from .const import CHANNEL_CACHE_TTL, MAX_SESSION_AGE, PAUSED_TIMEOUT, START_GRACE

_LOGGER = logging.getLogger(__name__)

_STOPPED_STATES = {STATE_IDLE, STATE_OFF, STATE_STANDBY, STATE_UNAVAILABLE}


@dataclass(slots=True)
class LiveSession:
    """A transcoded stream started by Home Assistant."""

    session_id: str
    channel: TabloChannel
    url: str
    player: str | None
    started: datetime
    unsub_state: CALLBACK_TYPE | None = None
    unsub_paused: CALLBACK_TYPE | None = None


class LiveTV:
    """Owns the channel cache and every stream this entry started."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TabloLocalClient,
        web: TabloWebClient | None,
    ) -> None:
        self.hass = hass
        self.client = client
        self.web = web
        self.sessions: dict[str, LiveSession] = {}
        self._channels: list[TabloChannel] = []
        self._channels_at: datetime | None = None
        self._unsub_sweep: CALLBACK_TYPE | None = None

    @callback
    def async_start_sweeper(self) -> None:
        self._unsub_sweep = async_track_time_interval(
            self.hass, self._async_sweep, MAX_SESSION_AGE / 16
        )

    async def async_channels(self) -> list[TabloChannel]:
        now = dt_util.utcnow()
        if (
            not self._channels
            or not self._channels_at
            or now - self._channels_at > CHANNEL_CACHE_TTL
        ):
            self._channels = await self.client.channels()
            self._channels_at = now
        return self._channels

    async def async_channel(self, object_id: str) -> TabloChannel | None:
        return next((c for c in await self.async_channels() if c.object_id == object_id), None)

    async def async_play_url(self, channel: TabloChannel, player: str | None) -> str:
        """Start a stream for ``channel`` and return a URL the player can open."""
        if self.web is None:
            # No transcoder: hand out the Tablo's own MPEG-2 HLS stream.
            return await self.client.watch(channel.object_id)

        if player:
            for sess in [s for s in self.sessions.values() if s.player == player]:
                await self.async_stop(sess.session_id)

        session_id, url = await self.web.start(channel.identifier)
        sess = LiveSession(session_id, channel, url, player, dt_util.utcnow())
        self.sessions[session_id] = sess
        try:
            await self.web.wait_ready(url)
        except TabloError:
            await self.async_stop(session_id)
            raise
        if player:
            sess.unsub_state = async_track_state_change_event(
                self.hass, [player], partial(self._on_player, session_id)
            )
        _LOGGER.debug("Started %s on %s (%s)", channel.title, player, session_id)
        return url

    @callback
    def _on_player(self, session_id: str, event: Event[EventStateChangedData]) -> None:
        sess = self.sessions.get(session_id)
        new = event.data["new_state"]
        if sess is None or new is None:
            return
        if dt_util.utcnow() - sess.started < START_GRACE:
            return
        if new.state in _STOPPED_STATES:
            self.hass.async_create_task(self.async_stop(session_id))
        elif new.state == STATE_PAUSED:
            if sess.unsub_paused is None:
                sess.unsub_paused = async_call_later(
                    self.hass, PAUSED_TIMEOUT, partial(self._on_paused_timeout, session_id)
                )
        elif sess.unsub_paused is not None:
            sess.unsub_paused()
            sess.unsub_paused = None

    @callback
    def _on_paused_timeout(self, session_id: str, _now: datetime) -> None:
        if sess := self.sessions.get(session_id):
            sess.unsub_paused = None
        self.hass.async_create_task(self.async_stop(session_id))

    async def async_stop(self, session_id: str) -> None:
        sess = self.sessions.pop(session_id, None)
        if sess is None:
            return
        for unsub in (sess.unsub_state, sess.unsub_paused):
            if unsub:
                unsub()
        if self.web is not None:
            try:
                await self.web.stop(session_id)
            except TabloError as err:
                _LOGGER.warning("Could not stop live TV session %s: %s", session_id, err)
        _LOGGER.debug("Stopped %s (%s)", sess.channel.title, session_id)

    async def async_stop_all(self) -> None:
        for session_id in list(self.sessions):
            await self.async_stop(session_id)

    async def _async_sweep(self, _now: datetime | None = None) -> None:
        cutoff = dt_util.utcnow() - MAX_SESSION_AGE
        for sess in [s for s in self.sessions.values() if s.started < cutoff]:
            await self.async_stop(sess.session_id)

    async def async_shutdown(self) -> None:
        if self._unsub_sweep:
            self._unsub_sweep()
            self._unsub_sweep = None
        await self.async_stop_all()
