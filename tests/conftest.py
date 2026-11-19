"""Fixtures for Tablo tests. All data here is synthetic."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.tablo.const import DOMAIN

HOST = "192.0.2.10"  # RFC 5737 documentation address
PORT = 8887
BASE = f"http://{HOST}:{PORT}"
SERVER_ID = "SID_000000000001"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom_components in every test."""


def server_info() -> dict[str, Any]:
    return {
        "server_id": SERVER_ID,
        "name": "Test Tablo",
        "version": "2.2.58",
        "local_address": HOST,
        "setup_completed": True,
        "model": {"wifi": True, "tuners": 4, "type": "t4g4", "name": "Tablo 4G QUAD 128GB"},
        "availability": "ready",
        "product": "tablo",
    }


def tuners(recording: bool = False) -> list[dict[str, Any]]:
    idle = {"in_use": False, "channel": None, "recording": None, "channel_identifier": None}
    out = [dict(idle) for _ in range(8)]
    if recording:
        out[0] = {
            "in_use": True,
            "channel": "/guide/channels/100",
            "recording": "/recordings/series/episodes/500",
            "channel_identifier": "S00000_002_01",
        }
    return out


def harddrives() -> list[dict[str, Any]]:
    gib = 1024**3
    return [
        {
            "connected": True,
            "kind": "internal",
            "name": "Internal Flash (128 GB)",
            "size": 100 * gib,
            "usage": 70 * gib,
            "free": 30 * gib,
        }
    ]


def airing(start: datetime, minutes: int = 60, episode: str | None = "Pilot") -> dict[str, Any]:
    return {
        "airing_details": {
            "datetime": start.strftime("%Y-%m-%dT%H:%MZ"),
            "duration": minutes * 60,
            "show_title": "Example Show",
            "channel": {
                "channel": {"call_sign": "WXYZ", "major": 2, "minor": 1, "network": "TEST"}
            },
        },
        "episode": {"title": episode, "description": "Something happens."},
        "schedule": {"state": "scheduled"},
    }


def mock_device(
    aioclient_mock: AiohttpClientMocker,
    *,
    recording: bool = False,
    scheduled: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Register mocked responses for every endpoint the coordinator polls."""
    scheduled = scheduled or {}
    aioclient_mock.get(f"{BASE}/server/info", json=server_info())
    aioclient_mock.get(f"{BASE}/server/tuners", json=tuners(recording))
    aioclient_mock.get(f"{BASE}/server/harddrives", json=harddrives())
    aioclient_mock.get(
        f"{BASE}/recordings/airings",
        json=[f"/recordings/series/episodes/{i}" for i in range(3)],
    )
    aioclient_mock.get(f"{BASE}/guide/airings", json=list(scheduled))
    aioclient_mock.post(f"{BASE}/batch", json=scheduled)


@pytest.fixture
def future_airings() -> dict[str, dict[str, Any]]:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    return {
        "/guide/series/episodes/2": airing(now + timedelta(days=2), episode=None),
        "/guide/series/episodes/1": airing(now + timedelta(hours=3)),
        "/guide/series/episodes/bad": {"airing_details": {}},
    }


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Tablo",
        unique_id=SERVER_ID,
        data={"host": HOST, "port": PORT},
    )


@pytest.fixture
def setup_entry() -> Generator[None]:
    """Avoid full setup when only testing the config flow."""
    from unittest.mock import patch

    with patch("custom_components.tablo.async_setup_entry", return_value=True):
        yield
