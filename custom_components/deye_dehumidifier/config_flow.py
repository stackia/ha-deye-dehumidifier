"""Config flow for Deye Dehumidifier integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.config_entries import ConfigFlow as ConfigFlowBase
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from libdeye.cloud_api import (
    DeyeCloudApi,
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)

from .const import CONF_AUTH_TOKEN, CONF_PASSWORD, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def validate_input(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate the user input with DeyeCloudApi."""

    errors: dict[str, str] = {}

    try:
        cloud_api = DeyeCloudApi(
            async_get_clientsession(hass),
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
        )
        await cloud_api.authenticate()
        user_input[CONF_AUTH_TOKEN] = cloud_api.auth_token
        return {
            "title": user_input[CONF_USERNAME],
            "unique_id": cloud_api.user_id,
            "data": user_input | {CONF_AUTH_TOKEN: cloud_api.auth_token},
        }
    except DeyeCloudApiCannotConnectError:
        errors["base"] = "cannot_connect"
    except DeyeCloudApiInvalidAuthError:
        errors["base"] = "invalid_auth"
    except Exception:
        _LOGGER.exception("Unexpected exception")
        errors["base"] = "unknown"

    return {"errors": errors}


class ConfigFlow(ConfigFlowBase, domain=DOMAIN):
    """Handle a config flow for Deye Dehumidifier."""

    VERSION = 1

    _reauth_entry: ConfigEntry | None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await validate_input(self.hass, user_input)
            if "errors" not in result:
                await self.async_set_unique_id(result["unique_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=result["title"],
                    data=result["data"],
                )
            else:
                errors = result["errors"]

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, user_input: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        assert self._reauth_entry
        username = self._reauth_entry.data[CONF_USERNAME]
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=STEP_REAUTH_DATA_SCHEMA,
                description_placeholders={"username": username},
            )
        user_input[CONF_USERNAME] = username
        result = await validate_input(self.hass, user_input)
        if "errors" in result:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=self.add_suggested_values_to_schema(
                    STEP_REAUTH_DATA_SCHEMA, user_input
                ),
                errors=result["errors"],
                description_placeholders={"username": username},
            )

        self.hass.config_entries.async_update_entry(
            self._reauth_entry,
            data=result["data"],
        )
        await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
        return self.async_abort(reason="reauth_successful")
