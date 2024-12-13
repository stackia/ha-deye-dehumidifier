"""The Deye Dehumidifier integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.event import async_call_later
from libdeye.cloud_api import (
    DeyeCloudApi,
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)
from libdeye.const import QUERY_DEVICE_STATE_COMMAND
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
    Platform.FAN,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Deye Dehumidifier from a config entry."""

    def on_auth_token_refreshed(auth_token: str) -> None:
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
        mqtt_info = await cloud_api.get_deye_platform_mqtt_info()
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
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient, cloud_api: DeyeCloudApi
    ) -> None:
        """Initialize the instance."""
        self._device = device
        self._mqtt_client = mqtt_client
        self._cloud_api = cloud_api
        self._attr_has_entity_name = True
        self._attr_available = self._device["online"]
        self._attr_unique_id = self._device["mac"]
        self.entity_id_base = f'deye_{self._device["mac"].lower()}'  # We will override HA generated entity ID
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device["mac"])},
            model=self._device["product_name"],
            manufacturer=MANUFACTURER,
            name=self._device["device_name"],
        )
        self._attr_should_poll = False
        self.subscription_muted: CALLBACK_TYPE | None = None
        # payload from the server sometimes are not a valid string
        if isinstance(self._device["payload"], str):
            self.device_state = DeyeDeviceState(self._device["payload"])
        else:
            self.device_state = DeyeDeviceState(
                "1411000000370000000000000000003C3C0000000000"  # 20°C/60%RH as the default state
            )

    def update_device_availability(self, available: bool) -> None:
        """Will be called when received new availability status."""
        if self.subscription_muted:
            return
        self._attr_available = available
        self.async_write_ha_state()

    def update_device_state(self, state: DeyeDeviceState) -> None:
        """Will be called when received new DeyeDeviceState."""
        if self.subscription_muted:
            return
        self.device_state = state
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        if self._device["platform"] == 1:
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

        await self.poll_device_state()
        self.async_on_remove(self.cancel_polling)

    @callback
    async def poll_device_state(self, now: datetime | None = None) -> None:
        """
        Some Deye devices have a very long heartbeat period. So polling is still necessary to get the latest state as
        quickly as possible.
        """
        if self._device["platform"] == 1:
            self._mqtt_client.publish_command(
                self._device["product_id"],
                self._device["device_id"],
                QUERY_DEVICE_STATE_COMMAND,
            )
        elif self._device["platform"] == 2:
            state = DeyeDeviceState(await self._cloud_api.get_fog_platform_device_properties(self._device["device_id"]))
            self.update_device_state(state)
        self.cancel_polling = async_call_later(self.hass, 10, self.poll_device_state)

    def mute_subscription_for_a_while(self) -> None:
        """Mute subscription for a while to avoid state bouncing."""
        if self.subscription_muted:
            self.subscription_muted()

        @callback
        def unmute(now: datetime) -> None:
            self.subscription_muted = None

        self.subscription_muted = async_call_later(self.hass, 10, unmute)

    async def publish_command(self, command: DeyeDeviceCommand) -> None:
        if self._device["platform"] == 1:
            """Publish a MQTT command to this device."""
            self._mqtt_client.publish_command(
                self._device["product_id"], self._device["device_id"], command.bytes()
            )
        elif self._device["platform"] == 2:
            """Publish a MQTT command to this device."""
            await self._cloud_api.set_fog_platform_device_properties(self._device["device_id"], command.json())
        self.async_write_ha_state()
        self.mute_subscription_for_a_while()
