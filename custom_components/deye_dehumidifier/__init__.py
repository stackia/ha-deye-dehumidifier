"""The Deye Dehumidifier integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from libdeye.cloud_api import (
    DeyeCloudApi,
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)
from libdeye.device_state_command import DeyeDeviceState
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo

from .const import (
    CONF_AUTH_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    DATA_CLOUD_API,
    DATA_COORDINATOR,
    DATA_DEVICE_LIST,
    DATA_MQTT_CLIENT,
    DOMAIN,
    MANUFACTURER,
)
from .data_coordinator import DeyeDataUpdateCoordinator

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
        for device in device_list:
            coordinator = DeyeDataUpdateCoordinator(
                hass, device, mqtt_client, cloud_api
            )
            device[DATA_COORDINATOR] = coordinator
            await device[DATA_COORDINATOR].async_config_entry_first_refresh()

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


class DeyeEntity(CoordinatorEntity, Entity):
    """Initiate Deye Base Class."""

    def __init__(
        self,
        device: DeyeApiResponseDeviceInfo,
        mqtt_client: DeyeMqttClient,
        cloud_api: DeyeCloudApi,
    ) -> None:
        """Initialize the instance."""
        self.coordinator = device[DATA_COORDINATOR]
        super().__init__(self.coordinator)
        self._device = device
        self._mqtt_client = mqtt_client
        self._cloud_api = cloud_api
        self._attr_has_entity_name = True
        self._device_available = self._device["online"]
        self._attr_unique_id = self._device["mac"]
        self.entity_id_base = f'deye_{self._device["mac"].lower()}'  # We will override HA generated entity ID
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device["mac"])},
            model=self._device["product_name"],
            manufacturer=MANUFACTURER,
            name=self._device["device_name"],
        )
        self._attr_should_poll = False
        # payload from the server sometimes are not a valid string
        if isinstance(self._device["payload"], str):
            self.device_state = DeyeDeviceState(self._device["payload"])
        else:
            self.device_state = DeyeDeviceState(
                "1411000000370000000000000000003C3C0000000000"  # 20°C/60%RH as the default state
            )
        remove_handle = self.coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        self.async_on_remove(remove_handle)

    async def publish_command_async(self, attribute, value):
        """Push command to a queue and deal with them together."""
        self.async_write_ha_state()
        self.hass.bus.fire(
            "call_humidifier_method", {"device_id": self._device["device_id"], "prop": attribute, "value": value}
        )
        await self.coordinator.async_request_refresh()

    @property
    def available(self):
        return self._device_available

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.device_state = self.coordinator.data
        self._device_available = self.coordinator.device_available
        super()._handle_coordinator_update()
