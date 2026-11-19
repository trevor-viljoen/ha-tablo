"""Tests for the watch_channel action, channel picker and Apple TV handling."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.tablo.api import TabloConnectionError, TabloWebClient, TabloWebError
from custom_components.tablo.const import DOMAIN, START_GRACE
from homeassistant.components import media_source
from homeassistant.components.media_source import Unresolvable
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import TRANSCODER
from .test_live_tv import PLAYER, deletes, setup

SELECT = "select.test_tablo_live_tv_channel"
URL = f"{TRANSCODER}/api/transcoded/s1/playlist.m3u8"


async def watch(hass: HomeAssistant, **data) -> None:
    await hass.services.async_call(
        DOMAIN, "watch_channel", {"entity_id": PLAYER, **data}, blocking=True
    )


# ---------------------------------------------------------------- picker


async def test_channel_select(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = await setup(hass, aioclient_mock)
    state = hass.states.get(SELECT)
    assert state.attributes["options"] == ["2.1 WXYZ (TEST)", "2.2 Movies Plus", "7.1 WAAA (ABC)"]
    assert state.state == "2.1 WXYZ (TEST)"
    assert entry.runtime_data.live.selected == "2.1 WXYZ (TEST)"

    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": "7.1 WAAA (ABC)"}, blocking=True
    )
    assert hass.states.get(SELECT).state == "7.1 WAAA (ABC)"
    assert entry.runtime_data.live.selected == "7.1 WAAA (ABC)"


async def test_channel_select_restores(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_restore_cache(hass, [State(SELECT, "2.2 Movies Plus")])
    entry = await setup(hass, aioclient_mock)
    assert hass.states.get(SELECT).state == "2.2 Movies Plus"
    assert entry.runtime_data.live.selected == "2.2 Movies Plus"


async def test_channel_select_without_lineup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, caplog: pytest.LogCaptureFixture
) -> None:
    with patch(
        "custom_components.tablo.api.TabloLocalClient.channels",
        side_effect=TabloConnectionError("down"),
    ):
        entry = await setup(hass, aioclient_mock)
    assert hass.states.get(SELECT).attributes["options"] == []
    assert entry.runtime_data.live.selected is None
    assert "Could not load the Tablo channel lineup" in caplog.text


# ---------------------------------------------------------------- action


@pytest.mark.parametrize("query", ["2.1", "wxyz", "2.1  WXYZ (test)", "11"])
async def test_watch_channel(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, query: str
) -> None:
    entry = await setup(hass, aioclient_mock)
    calls = async_mock_service(hass, "media_player", "play_media")
    await watch(hass, channel=query)
    assert len(calls) == 1
    assert calls[0].data == {
        "entity_id": PLAYER,
        "media_content_id": URL,
        "media_content_type": "video",
    }
    assert entry.runtime_data.live.sessions["s1"].channel.call_sign == "WXYZ"


async def test_watch_uses_picker(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = await setup(hass, aioclient_mock)
    async_mock_service(hass, "media_player", "play_media")
    await watch(hass)
    assert entry.runtime_data.live.sessions["s1"].channel.object_id == "11"


async def test_watch_validation(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = await setup(hass, aioclient_mock)
    with pytest.raises(ServiceValidationError, match="No channel matches"):
        await watch(hass, channel="99.9")
    entry.runtime_data.live.selected = None
    with pytest.raises(ServiceValidationError, match="No channel given"):
        await watch(hass)
    with pytest.raises(ServiceValidationError, match="No loaded Tablo"):
        await watch(hass, channel="2.1", config_entry_id="nope")


async def test_watch_needs_entry_when_several(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock)
    other = SimpleNamespace(entry_id="other", state=entry.state)
    with patch.object(hass.config_entries, "async_entries", return_value=[entry, other]):
        with pytest.raises(ServiceValidationError, match="Several Tablos"):
            await watch(hass, channel="2.1")
        async_mock_service(hass, "media_player", "play_media")
        await watch(hass, channel="2.1", config_entry_id=entry.entry_id)
    assert "s1" in entry.runtime_data.live.sessions


async def test_watch_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = await setup(hass, aioclient_mock)
    live = entry.runtime_data.live

    live._channels_at = None
    with (
        patch(
            "custom_components.tablo.api.TabloLocalClient.channels",
            side_effect=TabloConnectionError("down"),
        ),
        pytest.raises(HomeAssistantError, match="Could not load channels"),
    ):
        await watch(hass, channel="2.1")

    with (
        patch.object(TabloWebClient, "wait_ready", side_effect=TabloWebError("slow")),
        pytest.raises(HomeAssistantError, match=r"Could not start 2\.1 WXYZ"),
    ):
        await watch(hass, channel="2.1")
    assert live.sessions == {}


async def test_watch_player_failure_stops_stream(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, caplog: pytest.LogCaptureFixture
) -> None:
    entry = await setup(hass, aioclient_mock)

    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("player said no") from ValueError("got error -1 (TEST)")

    hass.services.async_register("media_player", "play_media", fail)
    await watch(hass, channel="2.1")  # returns once the stream is handed off
    await hass.async_block_till_done()
    assert entry.runtime_data.live.sessions == {}
    assert deletes(aioclient_mock) == [f"{TRANSCODER}/api/stream/s1"]
    assert "could not play live TV: player said no (ValueError: got error -1 (TEST))" in caplog.text


async def test_old_handoff_failing_keeps_new_stream(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A replaced stream's play_media erroring must not stop the new stream."""
    entry = await setup(hass, aioclient_mock)
    live = entry.runtime_data.live
    gate = asyncio.Event()

    async def slow_then_fail(call: ServiceCall) -> None:
        await gate.wait()
        raise HomeAssistantError("replaced")

    hass.services.async_register("media_player", "play_media", slow_then_fail)
    await watch(hass, channel="2.1")
    first = next(iter(live.sessions.values()))
    await live.async_stop(first.session_id)
    live.sessions["s2"] = replace(first, session_id="s2")  # a newer stream on the player
    gate.set()
    await hass.async_block_till_done()
    assert "s2" in live.sessions


async def test_watch_without_transcoder(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await setup(hass, aioclient_mock, transcode=False)
    aioclient_mock.post(
        "http://192.0.2.10:8887/guide/channels/11/watch",
        json={"playlist_url": "http://192.0.2.10/pl.m3u8"},
    )

    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("nope")

    hass.services.async_register("media_player", "play_media", fail)
    await watch(hass, channel="2.1")
    await hass.async_block_till_done()  # nothing to stop, must not raise


# --------------------------------------------------------- start watchdog


@pytest.mark.parametrize(("state", "kept"), [("playing", True), ("idle", False), (None, False)])
async def test_stops_if_player_never_starts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    state: str | None,
    kept: bool,
) -> None:
    entry = await setup(hass, aioclient_mock)
    async_mock_service(hass, "media_player", "play_media")
    if state:
        hass.states.async_set(PLAYER, state)
    await watch(hass, channel="2.1")
    freezer.tick(START_GRACE + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert ("s1" in entry.runtime_data.live.sessions) is kept


async def test_grace_end_after_stop_is_noop(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock)
    entry.runtime_data.live._on_grace_end("gone", None)  # must not raise


async def test_double_tap_leaves_one_stream(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock)
    async_mock_service(hass, "media_player", "play_media")
    await watch(hass, channel="2.1")
    await watch(hass, channel="2.1")
    assert list(entry.runtime_data.live.sessions) == ["s1"]
    assert deletes(aioclient_mock) == [f"{TRANSCODER}/api/stream/s1"]


async def test_wait_ready_aborts_when_unwanted(hass: HomeAssistant) -> None:
    web = TabloWebClient(async_get_clientsession(hass), TRANSCODER)
    with pytest.raises(TabloWebError, match="stopped before it started"):
        await web.wait_ready(URL, still_wanted=lambda: False)


# ---------------------------------------------------- Apple TV media panel


async def test_media_panel_refuses_apple_tv(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock)
    reg = er.async_get(hass).async_get_or_create(
        "media_player", "apple_tv", "atv-1", suggested_object_id="bedroom"
    )
    with pytest.raises(Unresolvable, match="Tablo app"):
        await media_source.async_resolve_media(
            hass, f"media-source://{DOMAIN}/{entry.entry_id}/live/11", reg.entity_id
        )
    assert entry.runtime_data.live.sessions == {}
    assert not any(c[0] == "POST" and "/api/stream" in str(c[1]) for c in aioclient_mock.mock_calls)


async def test_watch_refuses_apple_tv(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock)
    reg = er.async_get(hass).async_get_or_create(
        "media_player", "apple_tv", "atv-2", suggested_object_id="den"
    )
    with pytest.raises(ServiceValidationError, match="Tablo app"):
        await hass.services.async_call(
            DOMAIN, "watch_channel", {"entity_id": reg.entity_id, "channel": "2.1"}, blocking=True
        )
    assert entry.runtime_data.live.sessions == {}
