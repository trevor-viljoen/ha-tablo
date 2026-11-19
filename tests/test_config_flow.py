"""Tests for the Tablo config flow."""

from __future__ import annotations

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.tablo.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import BASE, HOST, PORT, SERVER_ID, server_info

pytestmark = pytest.mark.usefixtures("setup_entry")


async def test_user_flow_success(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/server/info", json=server_info())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": PORT}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Tablo"
    assert result["data"] == {"host": HOST, "port": PORT}
    assert result["result"].unique_id == SERVER_ID


@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"status": 401}, "invalid_auth"),
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect"),
        ({"status": 500}, "cannot_connect"),
    ],
)
async def test_user_flow_errors_then_recover(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict,
    error: str,
) -> None:
    aioclient_mock.get(f"{BASE}/server/info", **mock_kwargs)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": PORT}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/server/info", json=server_info())
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": PORT}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_already_configured_updates_host(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SERVER_ID, data={"host": "192.0.2.99", "port": PORT}
    )
    entry.add_to_hass(hass)
    aioclient_mock.get(f"{BASE}/server/info", json=server_info())

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": PORT}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == HOST
