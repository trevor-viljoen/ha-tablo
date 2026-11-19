"""Live TV: channel lineup and stream session lifecycle."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from functools import partial

from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    SERVICE_PLAY_MEDIA,
    MediaType,
)
from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_IDLE,
    STATE_OFF,
    STATE_PAUSED,
    STATE_STANDBY,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
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
# States that mean the player never picked the stream up.
_NOT_STARTED_STATES = _STOPPED_STATES | {STATE_UNKNOWN}


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
    unsub_grace: CALLBACK_TYPE | None = None


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


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
        self.selected: str | None = None
        self._channels: list[TabloChannel] = []
        self._channels_at: datetime | None = None
        self._unsub_sweep: CALLBACK_TYPE | None = None
        self._locks: dict[str | None, asyncio.Lock] = {}

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

    async def async_find_channel(self, query: str) -> TabloChannel | None:
        """Find a channel by title, number ("5.1"), call sign or object id."""
        q = _norm(query)
        channels = await self.async_channels()
        for key in (
            lambda c: _norm(c.title),
            lambda c: c.number,
            lambda c: _norm(c.call_sign),
            lambda c: c.object_id,
        ):
            if match := next((c for c in channels if key(c) == q), None):
                return match
        return None

    async def async_play_url(self, channel: TabloChannel, player: str | None) -> str:
        """Start a stream for ``channel`` and return a URL the player can open.

        Only one stream per player is kept: starting a new one stops the old
        one. Requests for the same player are serialised so a double tap can't
        leave an orphaned stream holding a tuner.
        """
        if self.web is None:
            # No transcoder: hand out the Tablo's own MPEG-2 HLS stream.
            return await self.client.watch(channel.object_id)

        async with self._locks.setdefault(player, asyncio.Lock()):
            await self.async_stop_player(player)

            session_id, url = await self.web.start(channel.identifier)
            sess = LiveSession(session_id, channel, url, player, dt_util.utcnow())
            self.sessions[session_id] = sess
            try:
                await self.web.wait_ready(url, still_wanted=lambda: session_id in self.sessions)
            except TabloError:
                await self.async_stop(session_id)
                raise
            if player:
                sess.unsub_state = async_track_state_change_event(
                    self.hass, [player], partial(self._on_player, session_id)
                )
                sess.unsub_grace = async_call_later(
                    self.hass, START_GRACE, partial(self._on_grace_end, session_id)
                )
            _LOGGER.debug("Started %s on %s (%s)", channel.title, player, session_id)
            return url

    async def async_watch(self, channel: TabloChannel, player: str) -> None:
        """Start ``channel`` and send it to ``player`` as video.

        Returns once the stream is ready and has been handed to the player.
        Some players (Apple TV via pyatv) only return from play_media when the
        video ends, so the hand-off runs in the background.
        """
        url = await self.async_play_url(channel, player)
        session_id = next((s.session_id for s in self.sessions.values() if s.url == url), None)
        self.hass.async_create_background_task(
            self._async_send(player, url, session_id), f"tablo live TV on {player}"
        )

    async def _async_send(self, player: str, url: str, session_id: str | None) -> None:
        try:
            await self.hass.services.async_call(
                MP_DOMAIN,
                SERVICE_PLAY_MEDIA,
                {
                    ATTR_ENTITY_ID: player,
                    ATTR_MEDIA_CONTENT_ID: url,
                    ATTR_MEDIA_CONTENT_TYPE: MediaType.VIDEO,
                },
                blocking=True,
            )
        except Exception as err:
            causes, cause = [], err.__cause__
            while cause is not None and len(causes) < 3:
                causes.append(f"{type(cause).__name__}: {cause}")
                cause = cause.__cause__
            _LOGGER.warning(
                "%s could not play live TV: %s%s",
                player,
                err,
                f" ({'; '.join(causes)})" if causes else "",
            )
            if session_id is not None:
                await self.async_stop(session_id)

    @callback
    def _on_grace_end(self, session_id: str, _now: datetime) -> None:
        """Stop the stream if the player never started playing it."""
        sess = self.sessions.get(session_id)
        if sess is None:
            return
        sess.unsub_grace = None
        state = self.hass.states.get(sess.player) if sess.player else None
        if state is None or state.state in _NOT_STARTED_STATES:
            _LOGGER.debug("%s never started on %s; stopping", sess.channel.title, sess.player)
            self.hass.async_create_task(self.async_stop(session_id))

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
        for unsub in (sess.unsub_state, sess.unsub_paused, sess.unsub_grace):
            if unsub:
                unsub()
        if self.web is not None:
            try:
                await self.web.stop(session_id)
            except TabloError as err:
                _LOGGER.warning("Could not stop live TV session %s: %s", session_id, err)
        _LOGGER.debug("Stopped %s (%s)", sess.channel.title, session_id)

    async def async_stop_player(self, player: str | None) -> None:
        """Stop every stream started for ``player`` (None = untargeted)."""
        for sess in [s for s in self.sessions.values() if s.player == player]:
            await self.async_stop(sess.session_id)

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
