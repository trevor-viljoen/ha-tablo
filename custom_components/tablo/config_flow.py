"""Config flow for Tablo."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TabloAuthError, TabloError, TabloLocalClient
from .const import DEFAULT_PORT, DOMAIN


class TabloConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tablo."""

    VERSION = 1

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
