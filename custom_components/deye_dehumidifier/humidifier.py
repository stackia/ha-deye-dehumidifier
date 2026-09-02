"""Platform for dehumidifier humidifier entities."""

from typing import Any, override

from libdeye.cloud_api import DeyeApiResponseDeviceInfo
from libdeye.const import DeyeDeviceMode, get_product_feature_config

from homeassistant.components.humidifier import (
    MODE_AUTO,
    MODE_NORMAL,
    MODE_SLEEP,
    HumidifierAction,
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeyeConfigEntry, DeyeEntity
from .data_coordinator import DeyeDataUpdateCoordinator

MODE_AIR_PURIFIER = "air_purifier"
MODE_CLOTHES_DRYER = "clothes_dryer"
MODE_TURBO = "turbo"
MODE_MANUAL_PURIFIER = "manual_purifier"
MODE_SLEEP_PURIFIER = "sleep_purifier"
MODE_AUTO_PURIFIER = "auto_purifier"

# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeyeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add dehumidifiers for this config entry."""
    data = entry.runtime_data
    async_add_entities(
        [
            DeyeDehumidifier(
                data.coordinator_map[device["device_id"]],
                device,
            )
            for device in data.device_list
        ]
    )


class DeyeDehumidifier(DeyeEntity, HumidifierEntity):
    """Dehumidifier entity."""

    _attr_translation_key = "dehumidifier"
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_name = None  # Inherits from device name

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
    ) -> None:
        """Initialize the humidifier entity."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-dehumidifier"
        feature_config = get_product_feature_config(device["product_id"])
        if len(feature_config["mode"]) > 0:
            self._attr_supported_features = HumidifierEntityFeature.MODES
        self._attr_available_modes = list(
            map(deye_mode_to_hass_mode, feature_config["mode"])
        )
        self._attr_min_humidity = feature_config["min_target_humidity"]
        self._attr_max_humidity = feature_config["max_target_humidity"]
        # Deye UIs and official apps step target humidity in 5% increments.
        self._attr_target_humidity_step = 5.0
        self._attr_entity_picture = device["picture_v3"] or device["product_icon"]

    @property
    @override
    def target_humidity(self) -> int:
        """Return the humidity we try to reach."""
        return self.coordinator.data.state.target_humidity

    @property
    @override
    def current_humidity(self) -> int:
        """Return the current humidity."""
        return self.coordinator.data.state.environment_humidity

    @property
    @override
    def is_on(self) -> bool:
        """Return True if device is on."""
        return bool(self.coordinator.data.state.power_switch)

    @property
    @override
    def mode(self) -> str:
        """Return the working mode."""
        return deye_mode_to_hass_mode(self.coordinator.data.state.mode)

    @property
    @override
    def action(self) -> HumidifierAction:
        """Return the current humidifier action."""
        if not self.coordinator.data.state.power_switch:
            return HumidifierAction.OFF
        if self.coordinator.data.state.fan_running:
            return HumidifierAction.DRYING
        return HumidifierAction.IDLE

    @override
    async def async_set_mode(self, mode: str) -> None:
        """Set new working mode."""
        self.coordinator.data.state.mode = hass_mode_to_deye_mode(mode)
        await self.publish_command_from_current_state()

    @override
    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        self.coordinator.data.state.target_humidity = humidity
        await self.publish_command_from_current_state()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the device on."""
        self.coordinator.data.state.power_switch = True
        await self.publish_command_from_current_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the device off."""
        self.coordinator.data.state.power_switch = False
        await self.publish_command_from_current_state()


def deye_mode_to_hass_mode(mode: DeyeDeviceMode) -> str:
    """Map DeyeDeviceMode to HumidifierEntity mode."""
    if mode == DeyeDeviceMode.CLOTHES_DRYER_MODE:
        return MODE_CLOTHES_DRYER
    if mode == DeyeDeviceMode.AIR_PURIFIER_MODE:
        return MODE_AIR_PURIFIER
    if mode == DeyeDeviceMode.AUTO_MODE:
        return MODE_AUTO
    if mode == DeyeDeviceMode.SLEEP_MODE:
        return MODE_SLEEP
    if mode == DeyeDeviceMode.TURBO_MODE:
        return MODE_TURBO
    if mode == DeyeDeviceMode.MANUAL_PURIFIER_MODE:
        return MODE_MANUAL_PURIFIER
    if mode == DeyeDeviceMode.SLEEP_PURIFIER_MODE:
        return MODE_SLEEP_PURIFIER
    if mode == DeyeDeviceMode.AUTO_PURIFIER_MODE:
        return MODE_AUTO_PURIFIER
    return MODE_NORMAL


def hass_mode_to_deye_mode(mode: str) -> DeyeDeviceMode:
    """Map HumidifierEntity mode to DeyeDeviceMode."""
    if mode == MODE_CLOTHES_DRYER:
        return DeyeDeviceMode.CLOTHES_DRYER_MODE
    if mode == MODE_AIR_PURIFIER:
        return DeyeDeviceMode.AIR_PURIFIER_MODE
    if mode == MODE_AUTO:
        return DeyeDeviceMode.AUTO_MODE
    if mode == MODE_SLEEP:
        return DeyeDeviceMode.SLEEP_MODE
    if mode == MODE_TURBO:
        return DeyeDeviceMode.TURBO_MODE
    if mode == MODE_MANUAL_PURIFIER:
        return DeyeDeviceMode.MANUAL_PURIFIER_MODE
    if mode == MODE_SLEEP_PURIFIER:
        return DeyeDeviceMode.SLEEP_PURIFIER_MODE
    if mode == MODE_AUTO_PURIFIER:
        return DeyeDeviceMode.AUTO_PURIFIER_MODE
    return DeyeDeviceMode.MANUAL_MODE
