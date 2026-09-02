"""The Deye Dehumidifier integration."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import logging
from typing import Any, TypeVar, override

from libdeye.client import DeyeClient
from libdeye.cloud_api import (
    DeyeApiResponseDeviceInfo,
    DeyeCloudApi,
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import ssl

from .const import (
    CONF_AUTH_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    MANUFACTURER,
    is_known_dehumidifier_identifier,
)
from .data_coordinator import DeyeDataUpdateCoordinator, DeyeDeviceListCoordinator
from .issues import (
    MqttDisconnectMonitor,
    async_delete_entry_issues,
    async_sync_unknown_product_issues,
)
from .subentries import (
    async_ensure_device_subentries,
    async_migrate_v1_device_subentries,
    async_remove_stale_device_subentries,
    subentry_id_map as build_subentry_id_map,
)

PLATFORMS: list[Platform] = [
    Platform.HUMIDIFIER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.FAN,
]

_LOGGER = logging.getLogger(__name__)


def _wrap_command_exception(err: Exception) -> HomeAssistantError:
    """Convert a device command failure into a translated HomeAssistantError."""
    if isinstance(err, DeyeCloudApiCannotConnectError):
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_cannot_connect",
        )
    if isinstance(err, DeyeCloudApiInvalidAuthError):
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_invalid_auth",
        )
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="command_failed",
        translation_placeholders={"error": str(err) or type(err).__name__},
    )


@dataclass
class ConfigEntryData:
    """Runtime data stored on a config entry."""

    client: DeyeClient
    device_list: list[DeyeApiResponseDeviceInfo]
    coordinator_map: dict[str, DeyeDataUpdateCoordinator]
    device_list_coordinator: DeyeDeviceListCoordinator
    subentry_id_map: dict[str, str]
    mqtt_monitor: MqttDisconnectMonitor | None = None


type DeyeConfigEntry = ConfigEntry[ConfigEntryData]


async def async_setup_entry(hass: HomeAssistant, entry: DeyeConfigEntry) -> bool:
    """Set up Deye Dehumidifier from a config entry.

    The parent entry owns the cloud account and pooled MQTT clients.
    Each dehumidifier is a config subentry; coordinators and entities
    follow the cloud device list and those subentries.
    """

    def on_auth_token_refreshed(auth_token: str) -> None:
        hass.config_entries.async_update_entry(
            entry, data=entry.data | {CONF_AUTH_TOKEN: auth_token}
        )

    cloud_api = DeyeCloudApi(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data[CONF_AUTH_TOKEN],
    )
    cloud_api.on_auth_token_refreshed = on_auth_token_refreshed
    client = DeyeClient(cloud_api, ssl.get_default_context())
    coordinator_map: dict[str, DeyeDataUpdateCoordinator] = {}
    device_list: list[DeyeApiResponseDeviceInfo] = []
    device_list_coordinator = DeyeDeviceListCoordinator(
        hass, entry, client, coordinator_map, device_list
    )

    try:
        await device_list_coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed, ConfigEntryNotReady:
        await device_list_coordinator.async_shutdown()
        for coordinator in list(coordinator_map.values()):
            await coordinator.async_shutdown()
        client.disconnect()
        raise

    created = async_ensure_device_subentries(hass, entry, device_list)
    if created:
        _LOGGER.debug(
            "Created %s dehumidifier subentries for %s",
            len(created),
            entry.title,
        )

    mqtt_monitor = MqttDisconnectMonitor(hass, entry.entry_id, client)
    entry.runtime_data = ConfigEntryData(
        client=client,
        device_list=device_list,
        coordinator_map=coordinator_map,
        device_list_coordinator=device_list_coordinator,
        subentry_id_map=build_subentry_id_map(entry),
        mqtt_monitor=mqtt_monitor,
    )

    async_sync_unknown_product_issues(hass, entry.entry_id, device_list)
    mqtt_monitor.async_start()

    @callback
    def _async_sync_subentries() -> None:
        data = entry.runtime_data
        async_ensure_device_subentries(hass, entry, data.device_list)
        async_remove_stale_device_subentries(
            hass, entry, {device["device_id"] for device in data.device_list}
        )
        data.subentry_id_map.clear()
        data.subentry_id_map.update(build_subentry_id_map(entry))

    @callback
    def _async_sync_issues() -> None:
        async_sync_unknown_product_issues(
            hass, entry.entry_id, entry.runtime_data.device_list
        )

    entry.async_on_unload(
        device_list_coordinator.async_add_listener(_async_sync_subentries)
    )
    entry.async_on_unload(
        device_list_coordinator.async_add_listener(_async_sync_issues)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry to the current version."""
    _LOGGER.debug(
        "Migrating configuration from version %s.%s",
        entry.version,
        entry.minor_version,
    )

    if entry.version > 2:
        return False

    if entry.version < 2:
        created = await async_migrate_v1_device_subentries(hass, entry)
        hass.config_entries.async_update_entry(entry, version=2)
        _LOGGER.debug(
            "Migrated %s dehumidifier subentries for %s",
            len(created),
            entry.title,
        )

    _LOGGER.debug(
        "Migration to configuration version %s.%s successful",
        entry.version,
        entry.minor_version,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DeyeConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = entry.runtime_data
        if data.mqtt_monitor is not None:
            data.mqtt_monitor.async_stop()
        async_delete_entry_issues(hass, entry.entry_id)
        await data.device_list_coordinator.async_shutdown()
        for coordinator in data.coordinator_map.values():
            await coordinator.async_shutdown()
        data.client.disconnect()

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: DeyeConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deleting a device that is no longer on the Deye account."""
    data = getattr(entry, "runtime_data", None)
    if data is None:
        return True
    current_macs = {device["mac"] for device in data.device_list}
    return not is_known_dehumidifier_identifier(device_entry.identifiers, current_macs)


_T = TypeVar("_T")


def async_setup_dynamic_entities(
    hass: HomeAssistant,
    config_entry: DeyeConfigEntry,
    async_add_entities: Callable[..., Any],
    entity_factory: Callable[
        [DeyeDataUpdateCoordinator, DeyeApiResponseDeviceInfo], Sequence[_T]
    ],
) -> None:
    """Add entities now and whenever a new dehumidifier is discovered."""
    data = config_entry.runtime_data
    known_devices: set[str] = set()

    @callback
    def _async_add_new_devices() -> None:
        current_ids = {device["device_id"] for device in data.device_list}
        known_devices.intersection_update(current_ids)
        by_subentry: dict[str, list[_T]] = {}
        for device in data.device_list:
            device_id = device["device_id"]
            if device_id in known_devices:
                continue
            coordinator = data.coordinator_map.get(device_id)
            subentry_id = data.subentry_id_map.get(device_id)
            if coordinator is None or subentry_id is None:
                continue
            known_devices.add(device_id)
            by_subentry.setdefault(subentry_id, []).extend(
                entity_factory(coordinator, device)
            )
        for subentry_id, new_entities in by_subentry.items():
            async_add_entities(new_entities, config_subentry_id=subentry_id)

    _async_add_new_devices()
    config_entry.async_on_unload(
        data.device_list_coordinator.async_add_listener(_async_add_new_devices)
    )


def deye_device_configuration_url(
    _device: DeyeApiResponseDeviceInfo,
) -> str | None:
    """Return a stable Deye cloud/app configuration URL if one exists.

    Deye Smart (德业智能) is a mobile app. The end-user API host
    ``api.deye.com.cn`` is not a user-facing configuration UI, and
    deyecloud.com is the inverter portal (a different product line).
    Device-list entries do not include a web configuration URL, so this
    returns None rather than inventing a broken link.
    """
    return None


class DeyeEntity(CoordinatorEntity[DeyeDataUpdateCoordinator]):
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
        device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device["mac"])},
            model=self._device["product_name"],
            model_id=self._device["product_id"],
            serial_number=self._device["mac"],
            manufacturer=MANUFACTURER,
            name=self._device["device_name"],
        )
        if configuration_url := deye_device_configuration_url(self._device):
            device_info["configuration_url"] = configuration_url
        self._attr_device_info = device_info
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
        try:
            await self.coordinator.device.apply(
                command, baseline=self.coordinator.data.reported_state
            )
        except HomeAssistantError:
            raise
        except Exception as err:
            raise _wrap_command_exception(err) from err
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
