"""Tests for setup, entities, coordinator and calendar."""

from __future__ import annotations

from datetime import timedelta

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.tablo.const import DOMAIN, SCAN_INTERVAL
from custom_components.tablo.coordinator import _parse_airing
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .conftest import BASE, SERVER_ID, airing, mock_device


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_device(aioclient_mock)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_when_offline(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    aioclient_mock.get(f"{BASE}/server/info", status=500)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_idle_state(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_device(aioclient_mock)
    await _setup(hass, config_entry)

    assert hass.states.get("binary_sensor.test_tablo_recording").state == STATE_OFF
    tuners = hass.states.get("sensor.test_tablo_tuners_in_use")
    assert tuners.state == "0"
    assert tuners.attributes["tuners"] == 4
    assert hass.states.get("sensor.test_tablo_recordings").state == "3"
    assert hass.states.get("sensor.test_tablo_scheduled_recordings").state == "0"
    assert hass.states.get("sensor.test_tablo_next_recording").state == STATE_UNKNOWN
    assert float(hass.states.get("sensor.test_tablo_storage_free").state) == 30.0
    assert (
        hass.states.get("sensor.test_tablo_storage_free").attributes["unit_of_measurement"] == "GiB"
    )
    assert float(hass.states.get("sensor.test_tablo_storage_used").state) == 70.0
    assert hass.states.get("calendar.test_tablo_scheduled_recordings").state == STATE_OFF

    # The batch endpoint isn't called when nothing is scheduled.
    assert not any(c[1].path == "/batch" for c in aioclient_mock.mock_calls)


async def test_device_info(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_device(aioclient_mock)
    await _setup(hass, config_entry)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, SERVER_ID)})
    assert device.manufacturer == "Nuvyyo"
    assert device.model == "Tablo 4G QUAD 128GB"
    assert device.sw_version == "2.2.58"
    assert device.serial_number == SERVER_ID


async def test_recording_state(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_device(aioclient_mock, recording=True)
    await _setup(hass, config_entry)
    rec = hass.states.get("binary_sensor.test_tablo_recording")
    assert rec.state == STATE_ON
    assert rec.attributes["tuners"][0]["recording"] == "/recordings/series/episodes/500"
    assert hass.states.get("sensor.test_tablo_tuners_in_use").state == "1"


async def test_scheduled_and_calendar(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    future_airings,
) -> None:
    mock_device(aioclient_mock, scheduled=future_airings)
    await _setup(hass, config_entry)

    # The unparseable airing is dropped; the rest are sorted by start.
    assert hass.states.get("sensor.test_tablo_scheduled_recordings").state == "2"
    nxt = hass.states.get("sensor.test_tablo_next_recording")
    assert nxt.attributes["title"] == "Example Show"
    assert nxt.attributes["episode"] == "Pilot"
    assert nxt.attributes["channel"] == "2.1 WXYZ"
    assert dt_util.parse_datetime(nxt.state) > dt_util.utcnow()

    cal = hass.states.get("calendar.test_tablo_scheduled_recordings")
    assert cal.attributes["message"] == "Example Show: Pilot"
    assert cal.attributes["location"] == "2.1 WXYZ"

    start = dt_util.utcnow()
    resp = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": cal.entity_id,
            "start_date_time": start,
            "end_date_time": start + timedelta(days=7),
        },
        blocking=True,
        return_response=True,
    )
    events = resp[cal.entity_id]["events"]
    assert [e["summary"] for e in events] == ["Example Show: Pilot", "Example Show"]

    resp = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": cal.entity_id,
            "start_date_time": start,
            "end_date_time": start + timedelta(hours=1),
        },
        blocking=True,
        return_response=True,
    )
    assert resp[cal.entity_id]["events"] == []


async def test_becomes_unavailable_then_recovers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    mock_device(aioclient_mock)
    await _setup(hass, config_entry)
    assert hass.states.get("sensor.test_tablo_recordings").state == "3"

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/server/info", status=500)
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test_tablo_recordings").state == STATE_UNAVAILABLE

    aioclient_mock.clear_requests()
    mock_device(aioclient_mock)
    async_fire_time_changed(hass, dt_util.utcnow() + SCAN_INTERVAL * 2)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test_tablo_recordings").state == "3"


def test_parse_airing_variants() -> None:
    start = dt_util.utcnow().replace(second=0, microsecond=0)
    a = _parse_airing("/p", airing(start, minutes=30))
    assert a.end - a.start == timedelta(minutes=30)
    assert a.channel == "2.1 WXYZ"

    assert _parse_airing("/p", {}) is None
    assert _parse_airing("/p", {"airing_details": {"datetime": "not-a-date"}}) is None

    movie = {
        "airing_details": {"datetime": "2030-01-01T00:00Z", "duration": 5400},
        "movie_airing": {"title": "A Movie", "description": "Plot."},
    }
    m = _parse_airing("/m", movie)
    assert (m.title, m.description, m.channel, m.episode) == ("A Movie", "Plot.", None, None)

    no_major = airing(start)
    no_major["airing_details"]["channel"]["channel"] = {"call_sign": "STREAM"}
    assert _parse_airing("/p", no_major).channel == "STREAM"
