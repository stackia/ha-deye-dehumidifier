"""Platform for humidifier integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.humidifier import HumidifierDeviceClass, HumidifierEntity
from homeassistant.components.humidifier.const import (
    MODE_AUTO,
    MODE_SLEEP,
    HumidifierAction,
    HumidifierEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from libdeye.cloud_api import DeyeApiResponseDeviceInfo
from libdeye.const import DeyeDeviceMode, get_product_feature_config
from libdeye.device_state import DeyeDeviceState

from . import DATA_KEY, DeyeEntity
from .data_coordinator import DeyeDataUpdateCoordinator

MODE_MANUAL = "manual"
MODE_AIR_PURIFIER = "air_purifier"
MODE_CLOTHES_DRYER = "clothes_dryer"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add dehumidifiers for passed config_entry in HA."""
    data = hass.data[DATA_KEY][config_entry.entry_id]

    for device in data.device_list:
        deye_dehumidifier = DeyeDehumidifier(
            data.coordinator_map[device["device_id"]],
            device,
        )
        async_add_entities([deye_dehumidifier])


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
        self.entity_id = f"humidifier.{self.entity_id_base}_dehumidifier"
        feature_config = get_product_feature_config(device["product_id"])
        if len(feature_config["mode"]) > 0:
            self._attr_supported_features = HumidifierEntityFeature.MODES
        self._attr_available_modes = list(
            map(deye_mode_to_hass_mode, feature_config["mode"])
        )
        self._attr_min_humidity = feature_config["min_target_humidity"]
        self._attr_max_humidity = feature_config["max_target_humidity"]
        self._attr_entity_picture = device["picture_v3"] or device["product_icon"]

    @property
    def get_device_state(self) -> DeyeDeviceState:
        return self.coordinator.data.state

    @property
    def target_humidity(self) -> int:
        """Return the humidity we try to reach."""
        return self.coordinator.data.state.target_humidity

    @property
    def current_humidity(self) -> int:
        """Return the current humidity."""
        return self.coordinator.data.state.environment_humidity

    @property
    def is_on(self) -> bool:
        """Return True if device is on."""
        return self.coordinator.data.state.power_switch

    @property
    def mode(self) -> str:
        """Return the working mode."""
        return deye_mode_to_hass_mode(self.coordinator.data.state.mode)

    @property
    def action(self) -> HumidifierAction:
        if not self.coordinator.data.state.power_switch:
            return HumidifierAction.OFF
        elif self.coordinator.data.state.fan_running:
            return HumidifierAction.DRYING
        else:
            return HumidifierAction.IDLE

    async def async_set_mode(self, mode: str) -> None:
        """Set new working mode."""
        self.coordinator.data.state.mode = hass_mode_to_deye_mode(mode)
        await self.publish_command_from_current_state()

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        self.coordinator.data.state.target_humidity = humidity
        await self.publish_command_from_current_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the device on."""
        self.coordinator.data.state.power_switch = True
        await self.publish_command_from_current_state()

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
    return MODE_MANUAL


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
    return DeyeDeviceMode.MANUAL_MODE
