"""Config flow for Tablo."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TabloAuthError, TabloError, TabloLocalClient, TabloWebClient
from .const import CONF_TRANSCODE_URL, DEFAULT_PORT, DOMAIN


class TabloConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tablo."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TabloOptionsFlow:
        return TabloOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = TabloLocalClient(
                async_get_clientsession(self.hass),
                user_input[CONF_HOST],
                user_input[CONF_PORT],
            )
            try:
                info = await client.server_info()
            except TabloAuthError:
                errors["base"] = "invalid_auth"
            except TabloError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info["server_id"])
                self._abort_if_unique_id_configured(updates=user_input)
                return self.async_create_entry(title=info.get("name") or "Tablo", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class TabloOptionsFlow(OptionsFlow):
    """Configure the optional tablo-web transcoder used for live TV."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = (user_input.get(CONF_TRANSCODE_URL) or "").strip().rstrip("/")
            if not url:
                return self.async_create_entry(data={})
            try:
                status = await TabloWebClient(async_get_clientsession(self.hass), url).status()
            except TabloError:
                errors[CONF_TRANSCODE_URL] = "cannot_connect"
            else:
                if status.get("authenticated"):
                    return self.async_create_entry(data={CONF_TRANSCODE_URL: url})
                errors[CONF_TRANSCODE_URL] = "transcoder_not_logged_in"

        current = (user_input or self.config_entry.options).get(CONF_TRANSCODE_URL, "")
        schema = vol.Schema(
            {vol.Optional(CONF_TRANSCODE_URL, description={"suggested_value": current}): str}
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
