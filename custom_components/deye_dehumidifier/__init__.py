"""The Deye Dehumidifier integration."""
from __future__ import annotations
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo, Entity
from libdeye.cloud_api import (
    DeyeCloudApi,
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)
from libdeye.device_state_command import DeyeDeviceCommand, DeyeDeviceState
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo

from .const import (
    CONF_AUTH_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    DATA_CLOUD_API,
    DATA_DEVICE_LIST,
    DATA_MQTT_CLIENT,
    DOMAIN,
    MANUFACTURER,
)

PLATFORMS: list[Platform] = [
    Platform.HUMIDIFIER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Deye Dehumidifier from a config entry."""

    def on_auth_token_refreshed(auth_token: str):
        hass.config_entries.async_update_entry(
            entry, data=entry.data | {CONF_AUTH_TOKEN: auth_token}
        )

    try:
        cloud_api = DeyeCloudApi(
            async_get_clientsession(hass),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            entry.data[CONF_AUTH_TOKEN],
        )
        cloud_api.on_auth_token_refreshed = on_auth_token_refreshed
        mqtt_info = await cloud_api.get_mqtt_info()
        mqtt_client = DeyeMqttClient(
            mqtt_info["mqtthost"],
            mqtt_info["sslport"],
            mqtt_info["loginname"],
            mqtt_info["password"],
            mqtt_info["endpoint"],
        )
        mqtt_client.connect()
        device_list = list(
            filter(
                lambda d: d["product_type"] == "dehumidifier",
                await cloud_api.get_device_list(),
            )
        )
    except DeyeCloudApiInvalidAuthError as err:
        raise ConfigEntryAuthFailed from err
    except DeyeCloudApiCannotConnectError as err:
        raise ConfigEntryNotReady from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLOUD_API: cloud_api,
        DATA_MQTT_CLIENT: mqtt_client,
        DATA_DEVICE_LIST: device_list,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        mqtt_client: DeyeMqttClient = data[DATA_MQTT_CLIENT]
        mqtt_client.disconnect()

    return unload_ok


class DeyeEntity(Entity):
    """Initiate Deye Base Class."""

    def __init__(
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient
    ) -> None:
        """Initialize the instance."""
        _LOGGER.warning("Device: %s", device)
        _LOGGER.warning("Device payload: %s", device["payload"])
        self._device = device
        self._mqtt_client = mqtt_client
        self._attr_has_entity_name = True
        self._attr_available = self._device["online"]
        self._attr_unique_id = self._device["mac"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device["mac"])},
            model=self._device["product_name"],
            manufacturer=MANUFACTURER,
            name=self._device["device_name"],
        )
        self._attr_should_poll = False
        self.device_state = DeyeDeviceState(self._device["payload"])

    def update_device_availability(self, available: bool):
        """Will be called when received new availability status."""
        self._attr_available = available
        self.async_write_ha_state()

    def update_device_state(self, state: DeyeDeviceState):
        """Will be called when received new DeyeDeviceState."""
        self.device_state = state
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        self.async_on_remove(
            self._mqtt_client.subscribe_availability_change(
                self._device["product_id"],
                self._device["device_id"],
                self.update_device_availability,
            )
        )
        self.async_on_remove(
            self._mqtt_client.subscribe_state_change(
                self._device["product_id"],
                self._device["device_id"],
                self.update_device_state,
            )
        )

    def publish_command(self, command: DeyeDeviceCommand) -> None:
        """Publish a MQTT command to this device."""
        self._mqtt_client.publish_command(
            self._device["product_id"], self._device["device_id"], command.bytes()
        )
        self.async_write_ha_state()
