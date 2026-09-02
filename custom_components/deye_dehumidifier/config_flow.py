"""Config flow for Deye Dehumidifier integration."""

from collections.abc import Mapping
import logging
from typing import Any, override

from libdeye.cloud_api import (
    DeyeApiResponseDeviceInfo,
    DeyeCloudApi,
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow as ConfigFlowBase,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    CONF_AUTH_TOKEN,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    SUBENTRY_TYPE_DEVICE,
)
from .subentries import (
    async_list_dehumidifier_infos,
    configured_device_ids,
    device_subentry_data,
)

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

    VERSION = 2

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        return {SUBENTRY_TYPE_DEVICE: DeviceSubentryFlowHandler}

    @override
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
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        reauth_entry = self._get_reauth_entry()
        username = reauth_entry.data[CONF_USERNAME]
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=STEP_REAUTH_DATA_SCHEMA,
                description_placeholders={"username": username},
            )
        user_input = {**user_input, CONF_USERNAME: username}
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

        return self.async_update_reload_and_abort(
            reauth_entry,
            data_updates={
                CONF_PASSWORD: result["data"][CONF_PASSWORD],
                CONF_AUTH_TOKEN: result["data"][CONF_AUTH_TOKEN],
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a reconfiguration flow initialized by the user."""
        reconfigure_entry = self._get_reconfigure_entry()
        username = reconfigure_entry.data[CONF_USERNAME]
        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=STEP_REAUTH_DATA_SCHEMA,
                description_placeholders={"username": username},
            )
        user_input = {**user_input, CONF_USERNAME: username}
        result = await validate_input(self.hass, user_input)
        if "errors" in result:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self.add_suggested_values_to_schema(
                    STEP_REAUTH_DATA_SCHEMA, user_input
                ),
                errors=result["errors"],
                description_placeholders={"username": username},
            )

        return self.async_update_reload_and_abort(
            reconfigure_entry,
            data_updates={
                CONF_PASSWORD: result["data"][CONF_PASSWORD],
                CONF_AUTH_TOKEN: result["data"][CONF_AUTH_TOKEN],
            },
        )


class DeviceSubentryFlowHandler(ConfigSubentryFlow):
    """Handle add and reconfigure flows for a dehumidifier subentry."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Let the user add a cloud dehumidifier that is not already configured."""
        entry = self._get_entry()
        errors, available = await self._async_available_devices(entry)
        if errors:
            return self.async_abort(reason=errors["base"])
        if not available:
            return self.async_abort(reason="no_devices")

        if user_input is not None:
            device = next(
                (
                    info
                    for info in available
                    if info["device_id"] == user_input[CONF_DEVICE_ID]
                ),
                None,
            )
            if device is None:
                return self.async_abort(reason="device_not_found")
            if device["device_id"] in configured_device_ids(entry):
                return self.async_abort(reason="already_configured")
            return self.async_create_entry(
                title=device["device_name"],
                data=device_subentry_data(device),
                unique_id=device["device_id"],
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=info["device_id"],
                                    label=f"{info['device_name']} ({info['mac']})",
                                )
                                for info in available
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Refresh a dehumidifier subentry from the current cloud device list."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        device_id = subentry.unique_id or subentry.data[CONF_DEVICE_ID]

        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "device_name": subentry.title,
                    "device_id": device_id,
                },
            )

        errors, devices = await self._async_account_devices(entry)
        if errors:
            return self.async_abort(reason=errors["base"])
        device = next(
            (info for info in devices if info["device_id"] == device_id),
            None,
        )
        if device is None:
            return self.async_abort(reason="device_not_found")

        return self.async_update_and_abort(
            entry,
            subentry,
            title=device["device_name"],
            data=device_subentry_data(device),
        )

    async def _async_available_devices(
        self, entry: ConfigEntry
    ) -> tuple[dict[str, str], list[DeyeApiResponseDeviceInfo]]:
        """Return dehumidifier rows that are not already a subentry."""
        errors, devices = await self._async_account_devices(entry)
        if errors:
            return errors, []
        already_added = configured_device_ids(entry)
        return {}, [info for info in devices if info["device_id"] not in already_added]

    async def _async_account_devices(
        self, entry: ConfigEntry
    ) -> tuple[dict[str, str], list[DeyeApiResponseDeviceInfo]]:
        """Fetch dehumidifier rows for the parent account."""
        try:
            return {}, await async_list_dehumidifier_infos(self.hass, entry)
        except DeyeCloudApiCannotConnectError:
            return {"base": "cannot_connect"}, []
        except DeyeCloudApiInvalidAuthError:
            return {"base": "invalid_auth"}, []
        except Exception:
            _LOGGER.exception("Unexpected exception while listing Deye devices")
            return {"base": "unknown"}, []
