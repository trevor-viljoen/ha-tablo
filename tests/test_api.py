"""Tests for the local API client."""

from __future__ import annotations

import hashlib
import hmac
import json

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.tablo.api import (
    _DEVICE_KEY,
    _HASH_KEY,
    TabloAuthError,
    TabloConnectionError,
    TabloLocalClient,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import BASE, HOST, PORT, server_info


def test_signature_matches_reference() -> None:
    """The Authorization header is the HMAC-MD5 of method, path, body hash and date."""
    body = json.dumps(["/a"])
    headers = TabloLocalClient._sign("POST", "/batch", body)
    expected = hmac.new(
        _HASH_KEY,
        f"POST\n/batch\n{hashlib.md5(body.encode()).hexdigest()}\n{headers['Date']}".encode(),
        hashlib.md5,
    ).hexdigest()
    assert headers["Authorization"] == f"tablo:{_DEVICE_KEY}:{expected}"
    assert headers["Date"].endswith("GMT")


def test_signature_empty_body() -> None:
    headers = TabloLocalClient._sign("GET", "/server/info", "")
    expected = hmac.new(
        _HASH_KEY, f"GET\n/server/info\n\n{headers['Date']}".encode(), hashlib.md5
    ).hexdigest()
    assert headers["Authorization"].endswith(expected)


async def test_server_info(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/server/info", json=server_info())
    client = TabloLocalClient(async_get_clientsession(hass), HOST, PORT)
    assert (await client.server_info())["server_id"] == server_info()["server_id"]
    _, _, _, headers = aioclient_mock.mock_calls[0]
    assert headers["Authorization"].startswith("tablo:")


async def test_scheduled_paths_uses_query(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/guide/airings", json=["/x"])
    client = TabloLocalClient(async_get_clientsession(hass), HOST, PORT)
    assert await client.scheduled_paths() == ["/x"]
    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert url.query["state"] == "scheduled"


async def test_batch_chunks(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/batch", json={"/p": {}})
    client = TabloLocalClient(async_get_clientsession(hass), HOST, PORT)
    await client.batch([f"/p/{i}" for i in range(120)])
    assert aioclient_mock.call_count == 3
    sizes = [len(json.loads(call[2])) for call in aioclient_mock.mock_calls]
    assert sizes == [50, 50, 20]


async def test_unauthorized(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/server/info", status=401)
    client = TabloLocalClient(async_get_clientsession(hass), HOST, PORT)
    with pytest.raises(TabloAuthError):
        await client.server_info()


async def test_http_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/server/info", status=500, text="boom")
    client = TabloLocalClient(async_get_clientsession(hass), HOST, PORT)
    with pytest.raises(TabloConnectionError, match="500"):
        await client.server_info()


async def test_connection_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/server/info", exc=aiohttp.ClientConnectionError())
    client = TabloLocalClient(async_get_clientsession(hass), HOST, PORT)
    with pytest.raises(TabloConnectionError):
        await client.server_info()


async def test_timeout(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/server/info", exc=TimeoutError())
    client = TabloLocalClient(async_get_clientsession(hass), HOST, PORT)
    with pytest.raises(TabloConnectionError):
        await client.server_info()
