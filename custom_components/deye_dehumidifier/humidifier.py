"""Platform for humidifier integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.humidifier import (
    MODE_AUTO,
    MODE_NORMAL,
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.components.humidifier.const import (  # pylint: disable=hass-component-root-import
    MODE_BOOST,
    MODE_COMFORT,
    MODE_SLEEP,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo, DeyeDeviceMode
from libdeye.utils import get_product_feature_config

from . import DeyeEntity
from .const import DATA_DEVICE_LIST, DATA_MQTT_CLIENT, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add dehumidifiers for passed config_entry in HA."""
    data = hass.data[DOMAIN][config_entry.entry_id]

    for device in data[DATA_DEVICE_LIST]:
        feature_config = get_product_feature_config(device["product_id"])
        if len(feature_config["fan_speed"]) == 0:
            async_add_entities([DeyeDehumidifier(device, data[DATA_MQTT_CLIENT])])


class DeyeDehumidifier(DeyeEntity, HumidifierEntity):
    """Dehumidifier entity. Models that doesn't support fan control will use this entity."""

    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER

    def __init__(
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient
    ) -> None:
        """Initialize the humidifier entity."""
        super().__init__(device, mqtt_client)
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
        self._attr_entity_picture = device["product_icon"]

    @property
    def target_humidity(self) -> int:
        """Return the humidity we try to reach."""
        return self.device_state.target_humidity

    @property
    def is_on(self) -> bool:
        """Return True if device is on."""
        return self.device_state.power_switch

    @property
    def mode(self) -> str | None:
        """Return the working mode."""
        return deye_mode_to_hass_mode(self.device_state.mode)

    async def async_set_mode(self, mode: str) -> None:
        """Set new working mode."""
        self.device_state.mode = hass_mode_to_deye_mode(mode)
        self.publish_command(self.device_state.to_command())

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        self.device_state.target_humidity = humidity
        self.publish_command(self.device_state.to_command())

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the device on."""
        self.device_state.power_switch = True
        self.publish_command(self.device_state.to_command())

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the device off."""
        self.device_state.power_switch = False
        self.publish_command(self.device_state.to_command())


def deye_mode_to_hass_mode(mode: DeyeDeviceMode) -> str:
    """Map DeyeDeviceMode to HumidifierEntity mode."""
    if mode == DeyeDeviceMode.CLOTHES_DRYER_MODE:
        return MODE_BOOST
    if mode == DeyeDeviceMode.AIR_PURIFIER_MODE:
        return MODE_COMFORT
    if mode == DeyeDeviceMode.AUTO_MODE:
        return MODE_AUTO
    if mode == DeyeDeviceMode.SLEEP_MODE:
        return MODE_SLEEP
    return MODE_NORMAL


def hass_mode_to_deye_mode(mode: str) -> DeyeDeviceMode:
    """Map HumidifierEntity mode to DeyeDeviceMode."""
    if mode == MODE_BOOST:
        return DeyeDeviceMode.CLOTHES_DRYER_MODE
    if mode == MODE_COMFORT:
        return DeyeDeviceMode.AIR_PURIFIER_MODE
    if mode == MODE_AUTO:
        return DeyeDeviceMode.AUTO_MODE
    if mode == MODE_SLEEP:
        return DeyeDeviceMode.SLEEP_MODE
    return DeyeDeviceMode.MANUAL_MODE
