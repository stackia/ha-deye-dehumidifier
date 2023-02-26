"""Platform for humidifier integration."""
from __future__ import annotations

from homeassistant.components.climate import (
    FAN_HIGH,
    FAN_LOW,
    FAN_MIDDLE,
    FAN_OFF,
    FAN_TOP,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_NONE,
    PRESET_SLEEP,
    SWING_OFF,
    SWING_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo, DeyeDeviceMode, DeyeFanSpeed
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
        if len(feature_config["fan_speed"]) > 0:
            async_add_entities(
                [DeyeAdvancedDehumidifier(device, data[DATA_MQTT_CLIENT])]
            )


class DeyeAdvancedDehumidifier(DeyeEntity, ClimateEntity):
    """Dehumidifier with fan controls. Only models supporting fan control will use this entity."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_swing_modes = [SWING_ON, SWING_OFF]

    def __init__(
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(device, mqtt_client)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-climate"
        feature_config = get_product_feature_config(device["product_id"])
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_HUMIDITY | ClimateEntityFeature.FAN_MODE
        )
        if len(feature_config["mode"]) > 0:
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
        if feature_config["oscillating"]:
            self._attr_supported_features |= ClimateEntityFeature.SWING_MODE
        self._attr_hvac_modes = [HVACMode.DRY, HVACMode.OFF]
        support_modes = feature_config["mode"].copy()
        if DeyeDeviceMode.AUTO_MODE in support_modes:
            self._attr_hvac_modes.append(HVACMode.AUTO)
            support_modes.remove(DeyeDeviceMode.AUTO_MODE)
        self._attr_preset_modes = list(
            map(deye_mode_to_hass_preset_mode, support_modes)
        )
        self._attr_fan_modes = list(
            map(deye_fan_speed_to_hass_fan_mode, feature_config["fan_speed"])
        )
        self._attr_min_humidity = feature_config["min_target_humidity"]
        self._attr_max_humidity = feature_config["max_target_humidity"]
        self._attr_entity_picture = device["product_icon"]

    @property
    def swing_mode(self) -> str | None:
        """Return swing mode based on oscillating_switch state."""
        return SWING_ON if self.device_state.oscillating_switch else SWING_OFF

    @property
    def current_temperature(self) -> float | None:
        """Return current environment temperature."""
        return self.device_state.environment_temperature

    @property
    def current_humidity(self) -> int | None:
        """Return current environment humidity."""
        return self.device_state.environment_humidity

    @property
    def target_humidity(self) -> int:
        """Return the humidity we try to reach."""
        return self.device_state.target_humidity

    @property
    def hvac_mode(self) -> HVACMode | str | None:
        """If the device supports AUTO mode, we'll use it as an HVAC mode here."""
        if not self.device_state.power_switch:
            return HVACMode.OFF
        if self.device_state.mode == DeyeDeviceMode.AUTO_MODE:
            return HVACMode.AUTO
        return HVACMode.DRY

    @property
    def hvac_action(self) -> HVACAction | str | None:
        """If the fan is not running but the power is on, we'll return IDLE here."""
        if not self.device_state.power_switch:
            return HVACAction.OFF
        return HVACAction.DRYING if self.device_state.fan_running else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        return deye_mode_to_hass_preset_mode(self.device_state.mode)

    @property
    def fan_mode(self) -> str | None:
        """Return the fan setting."""
        return deye_fan_speed_to_hass_fan_mode(self.device_state.fan_speed)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing operation."""
        self.device_state.oscillating_switch = swing_mode == SWING_ON
        self.publish_command(self.device_state.to_command())

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        self.device_state.target_humidity = humidity
        self.publish_command(self.device_state.to_command())

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        self.device_state.power_switch = hvac_mode != HVACMode.OFF
        if hvac_mode == HVACMode.AUTO:
            self.device_state.mode = DeyeDeviceMode.AUTO_MODE
        self.publish_command(self.device_state.to_command())

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new target preset mode."""
        self.device_state.mode = hass_preset_mode_to_deye_mode(preset_mode)
        self.publish_command(self.device_state.to_command())

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        self.device_state.fan_speed = hass_fan_mode_to_deye_fan_speed(fan_mode)
        self.publish_command(self.device_state.to_command())


def deye_mode_to_hass_preset_mode(mode: DeyeDeviceMode) -> str:
    """Map DeyeDeviceMode to ClimateEntity preset mode."""
    if mode == DeyeDeviceMode.CLOTHES_DRYER_MODE:
        return PRESET_BOOST
    if mode == DeyeDeviceMode.AIR_PURIFIER_MODE:
        return PRESET_COMFORT
    if mode == DeyeDeviceMode.SLEEP_MODE:
        return PRESET_SLEEP
    return PRESET_NONE


def hass_preset_mode_to_deye_mode(mode: str) -> DeyeDeviceMode:
    """Map ClimateEntity preset mode to DeyeDeviceMode."""
    if mode == PRESET_BOOST:
        return DeyeDeviceMode.CLOTHES_DRYER_MODE
    if mode == PRESET_COMFORT:
        return DeyeDeviceMode.AIR_PURIFIER_MODE
    if mode == PRESET_SLEEP:
        return DeyeDeviceMode.SLEEP_MODE
    return DeyeDeviceMode.MANUAL_MODE


def deye_fan_speed_to_hass_fan_mode(fan_speed: DeyeFanSpeed) -> str:
    """Map DeyeFanSpeed to ClimateEntity fan mode."""
    if fan_speed == DeyeFanSpeed.LOW:
        return FAN_LOW
    if fan_speed == DeyeFanSpeed.MIDDLE:
        return FAN_MIDDLE
    if fan_speed == DeyeFanSpeed.HIGH:
        return FAN_HIGH
    if fan_speed == DeyeFanSpeed.FULL:
        return FAN_TOP
    return FAN_OFF


def hass_fan_mode_to_deye_fan_speed(mode: str) -> DeyeFanSpeed:
    """Map ClimateEntity fan mode to DeyeFanSpeed."""
    if mode == FAN_LOW:
        return DeyeFanSpeed.LOW
    if mode == FAN_MIDDLE:
        return DeyeFanSpeed.MIDDLE
    if mode == FAN_HIGH:
        return DeyeFanSpeed.HIGH
    if mode == FAN_TOP:
        return DeyeFanSpeed.FULL
    return DeyeFanSpeed.STOPPED
