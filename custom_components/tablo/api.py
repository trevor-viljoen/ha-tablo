"""Async local API client for the Tablo 4th Gen DVR.

The device's local API (port 8887 by default) accepts HMAC-MD5 signed requests
using static keys from the Tablo mobile app, so no cloud login is required.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any

import aiohttp

_HASH_KEY = b"6l8jU5N43cEilqItmT3U2M2PFM3qPziilXqau9ys"
_DEVICE_KEY = "ljpg6ZkwShVv8aI12E2LP55Ep8vq1uYDPvX0DdTB"
_USER_AGENT = "Tablo-FAST/1.7.0 (Mobile; iPhone; iOS 18.4)"
_BATCH_SIZE = 50


class TabloError(Exception):
    """Base error for the Tablo client."""


class TabloConnectionError(TabloError):
    """The device could not be reached or returned an unexpected response."""


class TabloAuthError(TabloError):
    """The device rejected the request signature."""


class TabloLocalClient:
    """Minimal async client for the Tablo local API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = 8887,
        timeout: float = 20,
    ) -> None:
        self._session = session
        self._base = f"http://{host}:{port}"
        self._timeout = timeout

    @staticmethod
    def _sign(method: str, path: str, body: str) -> dict[str, str]:
        date = format_datetime(datetime.now(UTC), usegmt=True)
        body_hash = hashlib.md5(body.encode()).hexdigest() if body else ""
        payload = f"{method}\n{path}\n{body_hash}\n{date}".encode()
        sig = hmac.new(_HASH_KEY, payload, hashlib.md5).hexdigest()
        return {
            "Authorization": f"tablo:{_DEVICE_KEY}:{sig}",
            "Date": date,
            "User-Agent": _USER_AGENT,
            "Accept": "*/*",
        }

    async def _request(
        self,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        payload = json.dumps(body) if body is not None else ""
        headers = self._sign(method, path, payload)
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.request(
                    method,
                    self._base + path,
                    data=payload.encode() if payload else None,
                    params=params,
                    headers=headers,
                ) as resp:
                    if resp.status == 401:
                        raise TabloAuthError(f"{method} {path} rejected (401)")
                    if resp.status >= 400:
                        text = await resp.text()
                        raise TabloConnectionError(
                            f"{method} {path} failed ({resp.status}): {text[:200]}"
                        )
                    return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TabloConnectionError(f"{method} {path}: {err}") from err

    async def server_info(self) -> dict[str, Any]:
        """Return /server/info (id, name, version, model)."""
        return await self._request("GET", "/server/info")

    async def tuners(self) -> list[dict[str, Any]]:
        """Return tuner status list."""
        return await self._request("GET", "/server/tuners")

    async def harddrives(self) -> list[dict[str, Any]]:
        """Return storage devices with size/usage/free in bytes."""
        return await self._request("GET", "/server/harddrives")

    async def recording_paths(self) -> list[str]:
        """Return paths of all recorded airings."""
        return await self._request("GET", "/recordings/airings")

    async def scheduled_paths(self) -> list[str]:
        """Return guide paths of airings scheduled to record."""
        return await self._request("GET", "/guide/airings", params={"state": "scheduled"})

    async def batch(self, paths: list[str]) -> dict[str, Any]:
        """Fetch many objects at once via POST /batch."""
        out: dict[str, Any] = {}
        for i in range(0, len(paths), _BATCH_SIZE):
            chunk = paths[i : i + _BATCH_SIZE]
            out.update(await self._request("POST", "/batch", body=chunk))
        return out
