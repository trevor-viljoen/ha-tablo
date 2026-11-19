"""Async local API client for the Tablo 4th Gen DVR.

The device's local API (port 8887 by default) accepts HMAC-MD5 signed requests
using static keys from the Tablo mobile app, so no cloud login is required.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
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
        params: dict[str, str] | str | None = None,
        content_type: str | None = None,
    ) -> Any:
        payload = json.dumps(body) if body is not None else ""
        headers = self._sign(method, path, payload)
        if content_type:
            headers["Content-Type"] = content_type
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

    async def watch(self, channel_object_id: str) -> str:
        """Start a raw (MPEG-2) live stream on the device; return its HLS URL."""
        body = {
            "bandwidth": None,
            "extra": {
                "limitedAdTracking": 1,
                "deviceOSVersion": "16.6",
                "lang": "en_US",
                "height": 1080,
                "deviceId": "00000000-0000-0000-0000-000000000000",
                "width": 1920,
                "deviceModel": "iPhone10,1",
                "deviceMake": "Apple",
                "deviceOS": "iOS",
            },
            "device_id": "home-assistant",
            "platform": "ios",
        }
        data = await self._request(
            "POST",
            f"/guide/channels/{channel_object_id}/watch",
            body=body,
            params="lh",
            content_type="application/x-www-form-urlencoded",
        )
        url = data.get("playlist_url") if isinstance(data, dict) else None
        if not url:
            raise TabloConnectionError("Tablo did not return a playlist URL")
        return url

    async def channels(self) -> list[TabloChannel]:
        """Return the device's OTA channel lineup, sorted by channel number."""
        paths = await self._request("GET", "/guide/channels")
        details = await self.batch(paths) if paths else {}
        out: list[TabloChannel] = []
        for path, obj in details.items():
            ch = (obj or {}).get("channel") if isinstance(obj, dict) else None
            if not ch or not ch.get("channel_identifier"):
                continue
            logos = {lg.get("kind"): lg.get("url") for lg in ch.get("logos") or []}
            out.append(
                TabloChannel(
                    object_id=str(obj.get("object_id") or path.rsplit("/", 1)[-1]),
                    identifier=ch["channel_identifier"],
                    call_sign=ch.get("call_sign") or ch.get("name") or "",
                    major=int(ch.get("major") or 0),
                    minor=int(ch.get("minor") or 0),
                    network=ch.get("network") or "",
                    logo=logos.get("lightLarge") or logos.get("originalLarge"),
                )
            )
        out.sort(key=lambda c: (c.major, c.minor, c.call_sign))
        return out


@dataclass(frozen=True, slots=True)
class TabloChannel:
    """An over-the-air channel on the Tablo."""

    object_id: str
    identifier: str
    call_sign: str
    major: int
    minor: int
    network: str
    logo: str | None = None

    @property
    def number(self) -> str:
        return f"{self.major}.{self.minor}" if self.major else ""

    @property
    def title(self) -> str:
        name = f"{self.number} {self.call_sign}".strip()
        if self.network and self.network.upper() not in self.call_sign.upper():
            name += f" ({self.network})"
        return name


class TabloWebError(TabloError):
    """tablo-web could not start or stop a stream."""


class TabloWebClient:
    """Client for a tablo-web server, used to get Apple TV-friendly H.264 HLS.

    The Tablo sends OTA channels as MPEG-2, which many players (Apple TV,
    browsers, Chromecast) can't decode. tablo-web transcodes them to H.264.
    """

    def __init__(self, session: aiohttp.ClientSession, url: str, timeout: float = 45) -> None:
        self._session = session
        self.url = url.rstrip("/")
        self._timeout = timeout

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.request(method, self.url + path, **kwargs) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise TabloWebError(f"{method} {path} failed ({resp.status}): {text[:200]}")
                    return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TabloWebError(f"{method} {path}: {err}") from err

    async def status(self) -> dict[str, Any]:
        """Return tablo-web's auth status (is it logged in to a Tablo)."""
        return await self._call("GET", "/api/auth/status")

    async def start(self, identifier: str) -> tuple[str, str]:
        """Start a transcoded stream; return (session_id, absolute playlist URL)."""
        data = await self._call("POST", f"/api/stream/{identifier}", params={"transcode": "true"})
        return data["session_id"], self.url + data["stream_url"]

    async def stop(self, session_id: str) -> None:
        """Stop a stream and free its Tablo tuner."""
        await self._call("DELETE", f"/api/stream/{session_id}")

    async def wait_ready(
        self,
        playlist_url: str,
        timeout: float = 30,
        still_wanted: Callable[[], bool] | None = None,
    ) -> None:
        """Wait until the transcoder has written its first segment.

        ``still_wanted`` lets the caller abort early if the session was stopped
        while we were waiting.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            if still_wanted is not None and not still_wanted():
                raise TabloWebError("The stream was stopped before it started")
            try:
                async with self._session.get(playlist_url) as resp:
                    if resp.status == 200 and ".ts" in await resp.text():
                        return
            except aiohttp.ClientError:
                pass
            if loop.time() >= deadline:
                raise TabloWebError("Timed out waiting for the stream to start")
            await asyncio.sleep(1)
