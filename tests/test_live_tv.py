"""Tests for live TV: media source, transcoder sessions, button and options."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import aiohttp
import pytest
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.tablo.api import (
    TabloChannel,
    TabloConnectionError,
    TabloWebClient,
    TabloWebError,
)
from custom_components.tablo.const import (
    CHANNEL_CACHE_TTL,
    CONF_TRANSCODE_URL,
    DOMAIN,
    MAX_SESSION_AGE,
    PAUSED_TIMEOUT,
    START_GRACE,
)
from homeassistant.components import media_source
from homeassistant.components.media_source import Unresolvable
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.setup import async_setup_component

from .conftest import BASE, HOST, PORT, SERVER_ID, TRANSCODER, mock_device

PLAYER = "media_player.living_room"
PLAYLIST = "#EXTM3U\n#EXTINF:6.0,\n000.ts\n"


def mock_transcoder(aioclient_mock: AiohttpClientMocker, session_id: str = "s1") -> None:
    aioclient_mock.get(f"{TRANSCODER}/api/auth/status", json={"authenticated": True})
    aioclient_mock.post(
        f"{TRANSCODER}/api/stream/S2_002_01",
        json={
            "session_id": session_id,
            "stream_url": f"/api/transcoded/{session_id}/playlist.m3u8",
        },
    )
    aioclient_mock.get(f"{TRANSCODER}/api/transcoded/{session_id}/playlist.m3u8", text=PLAYLIST)
    aioclient_mock.delete(f"{TRANSCODER}/api/stream/{session_id}", json={"ok": True})


def deletes(aioclient_mock: AiohttpClientMocker) -> list[str]:
    return [str(c[1]) for c in aioclient_mock.mock_calls if c[0] == "DELETE"]


async def setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    *,
    transcode: bool = True,
) -> MockConfigEntry:
    mock_device(aioclient_mock)
    if transcode:
        mock_transcoder(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Tablo",
        unique_id=SERVER_ID,
        data={"host": HOST, "port": PORT},
        options={CONF_TRANSCODE_URL: TRANSCODER} if transcode else {},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "media_source", {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def channel_id(entry: MockConfigEntry, object_id: str = "11") -> str:
    return f"media-source://{DOMAIN}/{entry.entry_id}/live/{object_id}"


async def play(hass: HomeAssistant, entry: MockConfigEntry, player: str | None = PLAYER):
    return await media_source.async_resolve_media(hass, channel_id(entry), player)


# ---------------------------------------------------------------- browsing


async def test_browse_channels(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = await setup(hass, aioclient_mock)
    root = await media_source.async_browse_media(hass, f"media-source://{DOMAIN}")
    assert root.title == "Test Tablo Live TV"
    titles = [c.title for c in root.children]
    # Sorted by channel number; the entry with no identifier is skipped.
    assert titles == ["2.1 WXYZ (TEST)", "2.2 Movies Plus", "7.1 WAAA (ABC)"]
    first = root.children[0]
    assert first.can_play and not first.can_expand
    assert first.thumbnail == "https://example.com/logo.png"
    assert first.media_content_id == channel_id(entry)

    same = await media_source.async_browse_media(hass, f"media-source://{DOMAIN}/{entry.entry_id}")
    assert [c.title for c in same.children] == titles


async def test_browse_multiple_tablos(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    first = await setup(hass, aioclient_mock)
    second_host = "192.0.2.11"
    second_base = f"http://{second_host}:{PORT}"
    for path in ("/server/tuners", "/server/harddrives", "/recordings/airings"):
        aioclient_mock.get(second_base + path, json=[])
    aioclient_mock.get(
        f"{second_base}/server/info",
        json={"server_id": "SID_000000000002", "name": "Second Tablo", "model": {}},
    )
    aioclient_mock.get(f"{second_base}/guide/airings", json=[])
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Second Tablo",
        unique_id="SID_000000000002",
        data={"host": second_host, "port": PORT},
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    root = await media_source.async_browse_media(hass, f"media-source://{DOMAIN}")
    assert root.title == "Tablo"
    assert {c.title for c in root.children} == {"Test Tablo", "Second Tablo"}
    assert {c.media_content_id.rsplit("/", 1)[-1] for c in root.children} == {
        first.entry_id,
        second.entry_id,
    }


async def test_browse_unknown_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await setup(hass, aioclient_mock)
    with pytest.raises(Unresolvable):
        await media_source.async_browse_media(hass, f"media-source://{DOMAIN}/nope")


async def test_browse_channels_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await setup(hass, aioclient_mock)
    with (
        patch(
            "custom_components.tablo.api.TabloLocalClient.channels",
            side_effect=TabloConnectionError("down"),
        ),
        pytest.raises(Unresolvable, match="Could not load channels"),
    ):
        await media_source.async_browse_media(hass, f"media-source://{DOMAIN}")


async def test_channel_cache(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    await setup(hass, aioclient_mock)

    def lineup_calls() -> int:
        return sum(1 for c in aioclient_mock.mock_calls if c[1].path == "/guide/channels")

    await media_source.async_browse_media(hass, f"media-source://{DOMAIN}")
    await media_source.async_browse_media(hass, f"media-source://{DOMAIN}")
    assert lineup_calls() == 1
    freezer.tick(CHANNEL_CACHE_TTL + timedelta(minutes=1))
    await media_source.async_browse_media(hass, f"media-source://{DOMAIN}")
    assert lineup_calls() == 2


# ------------------------------------------------------- resolving / playing


async def test_play_direct_without_transcoder(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock, transcode=False)
    aioclient_mock.post(
        f"{BASE}/guide/channels/11/watch",
        json={"playlist_url": "http://192.0.2.10:80/stream/pl.m3u8?x"},
    )
    result = await play(hass, entry)
    assert result.url == "http://192.0.2.10:80/stream/pl.m3u8?x"
    assert result.mime_type == "application/vnd.apple.mpegurl"
    method, url, _body, headers = aioclient_mock.mock_calls[-1]
    assert (method, url.path) == ("POST", "/guide/channels/11/watch")
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert headers["Authorization"].startswith("tablo:")
    assert entry.runtime_data.live.sessions == {}


async def test_play_direct_no_playlist(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock, transcode=False)
    aioclient_mock.post(f"{BASE}/guide/channels/11/watch", json={"error": "no tuner"})
    with pytest.raises(Unresolvable, match="playlist"):
        await play(hass, entry)


@pytest.mark.parametrize("ident", ["garbage", "{entry}/vod/11", "{entry}/live/999"])
async def test_resolve_bad_identifiers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, ident: str
) -> None:
    entry = await setup(hass, aioclient_mock)
    with pytest.raises(Unresolvable):
        await media_source.async_resolve_media(
            hass, f"media-source://{DOMAIN}/{ident.format(entry=entry.entry_id)}", PLAYER
        )


async def test_play_transcoded(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = await setup(hass, aioclient_mock)
    result = await play(hass, entry)
    assert result.url == f"{TRANSCODER}/api/transcoded/s1/playlist.m3u8"
    sess = entry.runtime_data.live.sessions["s1"]
    assert (sess.player, sess.channel.call_sign) == (PLAYER, "WXYZ")
    start = next(c for c in aioclient_mock.mock_calls if c[0] == "POST" and "stream" in c[1].path)
    assert start[1].query["transcode"] == "true"


async def test_transcoder_not_ready_stops_session(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock)
    with (
        patch.object(TabloWebClient, "wait_ready", side_effect=TabloWebError("slow")),
        pytest.raises(Unresolvable),
    ):
        await play(hass, entry)
    assert entry.runtime_data.live.sessions == {}
    assert deletes(aioclient_mock) == [f"{TRANSCODER}/api/stream/s1"]


async def test_new_stream_on_same_player_replaces_old(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock)
    await play(hass, entry)
    await play(hass, entry)
    assert deletes(aioclient_mock) == [f"{TRANSCODER}/api/stream/s1"]
    assert list(entry.runtime_data.live.sessions) == ["s1"]


async def test_play_without_target_player_is_tracked_but_not_watched(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock)
    await play(hass, entry, None)
    sess = entry.runtime_data.live.sessions["s1"]
    assert sess.player is None and sess.unsub_state is None


# ------------------------------------------------------- session lifecycle


async def test_stops_when_player_stops(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass, aioclient_mock)
    hass.states.async_set(PLAYER, "playing")
    await play(hass, entry)

    # Within the start grace period, state blips are ignored.
    hass.states.async_set(PLAYER, "idle")
    await hass.async_block_till_done()
    assert "s1" in entry.runtime_data.live.sessions

    freezer.tick(START_GRACE + timedelta(seconds=1))
    hass.states.async_set(PLAYER, "playing")
    await hass.async_block_till_done()
    assert "s1" in entry.runtime_data.live.sessions

    hass.states.async_set(PLAYER, "off")
    await hass.async_block_till_done()
    assert entry.runtime_data.live.sessions == {}
    assert deletes(aioclient_mock) == [f"{TRANSCODER}/api/stream/s1"]


async def test_player_removed_is_ignored(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass, aioclient_mock)
    hass.states.async_set(PLAYER, "playing")
    await play(hass, entry)
    freezer.tick(START_GRACE + timedelta(seconds=1))
    hass.states.async_remove(PLAYER)
    await hass.async_block_till_done()
    assert "s1" in entry.runtime_data.live.sessions


async def test_paused_too_long_stops(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass, aioclient_mock)
    hass.states.async_set(PLAYER, "playing")
    await play(hass, entry)
    freezer.tick(START_GRACE + timedelta(seconds=1))

    hass.states.async_set(PLAYER, "paused")
    await hass.async_block_till_done()
    hass.states.async_set(PLAYER, "paused", {"position": 1})  # a second paused update
    await hass.async_block_till_done()

    freezer.tick(PAUSED_TIMEOUT + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert entry.runtime_data.live.sessions == {}


async def test_resume_cancels_pause_timer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass, aioclient_mock)
    hass.states.async_set(PLAYER, "playing")
    await play(hass, entry)
    freezer.tick(START_GRACE + timedelta(seconds=1))

    hass.states.async_set(PLAYER, "paused")
    await hass.async_block_till_done()
    hass.states.async_set(PLAYER, "playing")
    await hass.async_block_till_done()
    assert entry.runtime_data.live.sessions["s1"].unsub_paused is None

    freezer.tick(PAUSED_TIMEOUT + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert "s1" in entry.runtime_data.live.sessions


async def test_sweeper_stops_old_sessions(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass, aioclient_mock)
    await play(hass, entry, None)
    freezer.tick(MAX_SESSION_AGE + timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert entry.runtime_data.live.sessions == {}


async def test_stop_failure_still_forgets_session(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, caplog: pytest.LogCaptureFixture
) -> None:
    entry = await setup(hass, aioclient_mock)
    await play(hass, entry, None)
    aioclient_mock.clear_requests()
    aioclient_mock.delete(f"{TRANSCODER}/api/stream/s1", status=500)
    live = entry.runtime_data.live
    await live.async_stop("s1")
    await live.async_stop("unknown")  # no-op
    assert live.sessions == {}
    assert "Could not stop live TV session s1" in caplog.text


async def test_stop_button(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    entry = await setup(hass, aioclient_mock)
    await play(hass, entry)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.test_tablo_stop_live_tv"}, blocking=True
    )
    assert entry.runtime_data.live.sessions == {}


async def test_unload_stops_streams(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock)
    await play(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert deletes(aioclient_mock) == [f"{TRANSCODER}/api/stream/s1"]


# ------------------------------------------------------------- web client


async def test_web_wait_ready_times_out(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{TRANSCODER}/p.m3u8", status=404)
    web = TabloWebClient(async_get_clientsession(hass), TRANSCODER)
    with pytest.raises(TabloWebError, match="Timed out"):
        await web.wait_ready(f"{TRANSCODER}/p.m3u8", timeout=0)


async def test_web_wait_ready_retries(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{TRANSCODER}/p.m3u8", exc=aiohttp.ClientConnectionError())
    web = TabloWebClient(async_get_clientsession(hass), TRANSCODER)
    with (
        patch("custom_components.tablo.api.asyncio.sleep") as sleep,
        pytest.raises(TabloWebError),
    ):
        await web.wait_ready(f"{TRANSCODER}/p.m3u8", timeout=0.5)
    assert sleep.await_count >= 1


async def test_web_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{TRANSCODER}/api/auth/status", status=502, text="bad gateway")
    aioclient_mock.post(f"{TRANSCODER}/api/stream/X", exc=TimeoutError())
    web = TabloWebClient(async_get_clientsession(hass), TRANSCODER + "/")
    assert web.url == TRANSCODER
    with pytest.raises(TabloWebError, match="502"):
        await web.status()
    with pytest.raises(TabloWebError):
        await web.start("X")


def test_channel_titles() -> None:
    def ch(sign: str, major: int = 2, network: str = "") -> TabloChannel:
        return TabloChannel("1", "S", sign, major, 1, network)

    assert ch("WXYZ", network="NBC").title == "2.1 WXYZ (NBC)"
    assert ch("KFOR", network="kfor").title == "2.1 KFOR"  # network already in call sign
    assert ch("STREAM", major=0).title == "STREAM"
    assert ch("STREAM", major=0).number == ""


# ---------------------------------------------------------------- options


async def _options(hass: HomeAssistant, entry: MockConfigEntry, url: str):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TRANSCODE_URL: url}
    )


async def test_options_set_transcoder(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock, transcode=False)
    mock_transcoder(aioclient_mock)
    result = await _options(hass, entry, TRANSCODER + "/ ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {CONF_TRANSCODE_URL: TRANSCODER}
    # The entry reloads and now uses the transcoder.
    assert entry.runtime_data.live.web is not None


async def test_options_clear_transcoder(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup(hass, aioclient_mock)
    result = await _options(hass, entry, "")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {}
    assert entry.runtime_data.live.web is None


@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"json": {"authenticated": False}}, "transcoder_not_logged_in"),
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect"),
    ],
)
async def test_options_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_kwargs: dict, error: str
) -> None:
    entry = await setup(hass, aioclient_mock, transcode=False)
    aioclient_mock.get(f"{TRANSCODER}/api/auth/status", **mock_kwargs)
    result = await _options(hass, entry, TRANSCODER)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_TRANSCODE_URL: error}
