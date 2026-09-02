"""The Deye Dehumidifier integration."""

from dataclasses import dataclass
import logging
from typing import override

from libdeye.cloud_api import (
    DeyeApiResponseDeviceInfo,
    DeyeCloudApi,
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)
from libdeye.mqtt_client import BaseDeyeMqttClient, mqtt_client_type_for_platform

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import ssl
from homeassistant.util.hass_dict import HassKey

from .const import CONF_AUTH_TOKEN, CONF_PASSWORD, CONF_USERNAME, DOMAIN, MANUFACTURER
from .data_coordinator import DeyeDataUpdateCoordinator

PLATFORMS: list[Platform] = [
    Platform.HUMIDIFIER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.FAN,
]

_LOGGER = logging.getLogger(__name__)

DATA_KEY: HassKey[dict[str, ConfigEntryData]] = HassKey(DOMAIN)


@dataclass
class ConfigEntryData:
    """Runtime data stored on a config entry."""

    mqtt_clients: list[BaseDeyeMqttClient]
    device_list: list[DeyeApiResponseDeviceInfo]
    coordinator_map: dict[str, DeyeDataUpdateCoordinator]


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

        device_list = list(
            filter(
                # The product_type was initially set to "dehumidifier"
                # but at some point (around 06/18/2025) it was changed to "除湿机" or "其他"
                lambda d: (
                    d["product_type"] == "dehumidifier"
                    or d["product_type"] == "除湿机"
                    or d["product_type"] == "其他"
                ),
                await cloud_api.get_device_list(),
            )
        )

        tls_context = ssl.get_default_context()
        mqtt_clients_by_type: dict[type[BaseDeyeMqttClient], BaseDeyeMqttClient] = {}
        for device in device_list:
            client_cls = mqtt_client_type_for_platform(device["platform"])
            if client_cls not in mqtt_clients_by_type:
                client = client_cls(cloud_api, tls_context)
                await client.connect()
                mqtt_clients_by_type[client_cls] = client

        coordinator_map: dict[str, DeyeDataUpdateCoordinator] = {}
        for device in device_list:
            coordinator = DeyeDataUpdateCoordinator(
                hass,
                entry,
                device,
                mqtt_clients_by_type[mqtt_client_type_for_platform(device["platform"])],
                cloud_api,
            )
            await coordinator.async_config_entry_first_refresh()
            coordinator_map[device["device_id"]] = coordinator

    except DeyeCloudApiInvalidAuthError as err:
        raise ConfigEntryAuthFailed from err
    except DeyeCloudApiCannotConnectError as err:
        raise ConfigEntryNotReady from err

    hass.data.setdefault(DATA_KEY, {})
    hass.data[DATA_KEY][entry.entry_id] = ConfigEntryData(
        mqtt_clients=list(mqtt_clients_by_type.values()),
        device_list=device_list,
        coordinator_map=coordinator_map,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DATA_KEY].pop(entry.entry_id)
        for mqtt_client in data.mqtt_clients:
            mqtt_client.disconnect()

    return unload_ok


class DeyeEntity(CoordinatorEntity[DeyeDataUpdateCoordinator], Entity):
    """Initiate Deye Base Class."""

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
    ) -> None:
        """Initialize the instance."""
        super().__init__(coordinator)
        self._device = device
        self._attr_has_entity_name = True
        self._attr_unique_id = self._device["mac"]
        self.entity_id_base = f"deye_{self._device['mac'].lower()}"  # We will override HA generated entity ID
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device["mac"])},
            model=self._device["product_name"],
            model_id=self._device["product_id"],
            serial_number=self._device["mac"],
            manufacturer=MANUFACTURER,
            name=self._device["device_name"],
        )
        self._debounced_publish_command = Debouncer(
            hass=self.coordinator.hass,
            logger=_LOGGER,
            cooldown=2,
            immediate=True,
            background=True,
            function=self._publish_command,
        )
        if self.coordinator.config_entry:
            self.coordinator.config_entry.async_on_unload(
                self._debounced_publish_command.async_shutdown
            )

    async def _publish_command(self) -> None:
        """Publish commands to the device."""
        command = self.coordinator.data.state.to_command()
        await self.coordinator.mqtt_client.publish_command(
            self._device["product_id"],
            self._device["device_id"],
            command,
            baseline=self.coordinator.data.reported_state,
        )
        self.coordinator.sync_reported_state_after_publish()

    async def publish_command_from_current_state(self) -> None:
        """Publish a command generated from the current desired state.

        Should be called after modifying device state.
        """
        self.coordinator.mute_state_update_for_a_while()
        self.coordinator.async_update_listeners()
        await self._debounced_publish_command.async_call()

    @property
    @override
    def available(self) -> bool:
        """Return True if the device is available."""
        return self.coordinator.data.available
