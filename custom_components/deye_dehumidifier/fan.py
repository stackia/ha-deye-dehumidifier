"""Platform for dehumidifier fan entities."""

from typing import Any, override

from libdeye.cloud_api import DeyeApiResponseDeviceInfo
from libdeye.const import DeyeFanSpeed, get_product_feature_config

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from . import DATA_KEY, DeyeEntity
from .data_coordinator import DeyeDataUpdateCoordinator

# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0

PRESET_MODE_LOW = "low"
PRESET_MODE_MEDIUM = "medium"
PRESET_MODE_HIGH = "high"
PRESET_MODE_FULL = "full"
PRESET_MODE_AUTO = "auto"

_DEYE_FAN_SPEED_TO_PRESET: dict[DeyeFanSpeed, str] = {
    DeyeFanSpeed.LOW: PRESET_MODE_LOW,
    DeyeFanSpeed.MIDDLE: PRESET_MODE_MEDIUM,
    DeyeFanSpeed.HIGH: PRESET_MODE_HIGH,
    DeyeFanSpeed.FULL: PRESET_MODE_FULL,
    DeyeFanSpeed.AUTO: PRESET_MODE_AUTO,
}

_PRESET_TO_DEYE_FAN_SPEED: dict[str, DeyeFanSpeed] = {
    preset: speed for speed, preset in _DEYE_FAN_SPEED_TO_PRESET.items()
}


def deye_fan_speed_to_preset_mode(fan_speed: DeyeFanSpeed) -> str | None:
    """Map DeyeFanSpeed to a Home Assistant fan preset mode."""
    return _DEYE_FAN_SPEED_TO_PRESET.get(fan_speed)


def preset_mode_to_deye_fan_speed(preset_mode: str) -> DeyeFanSpeed:
    """Map a Home Assistant fan preset mode to DeyeFanSpeed."""
    if preset_mode not in _PRESET_TO_DEYE_FAN_SPEED:
        raise ValueError(f"Invalid preset mode: {preset_mode}")
    return _PRESET_TO_DEYE_FAN_SPEED[preset_mode]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add fans for passed config_entry in HA."""
    data = hass.data[DATA_KEY][config_entry.entry_id]
    async_add_entities(
        [
            DeyeFan(
                data.coordinator_map[device["device_id"]],
                device,
            )
            for device in data.device_list
            if len(get_product_feature_config(device["product_id"])["fan_speed"]) > 0
        ]
    )


class DeyeFan(DeyeEntity, FanEntity):
    """This will be provided in addition to the DeyeDehumidifier entity (only for models that supports fan control)."""

    _attr_translation_key = "fan"

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
    ) -> None:
        """Initialize the fan entity."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-fan"
        feature_config = get_product_feature_config(device["product_id"])
        self._attr_supported_features = (
            FanEntityFeature.SET_SPEED
            | FanEntityFeature.TURN_ON
            | FanEntityFeature.TURN_OFF
            | FanEntityFeature.PRESET_MODE
        )
        if feature_config["oscillating"]:
            self._attr_supported_features |= FanEntityFeature.OSCILLATE
        self._named_fan_speeds = feature_config["fan_speed"]
        self._attr_speed_count = len(self._named_fan_speeds)
        self._attr_preset_modes = [
            _DEYE_FAN_SPEED_TO_PRESET[speed]
            for speed in self._named_fan_speeds
            if speed in _DEYE_FAN_SPEED_TO_PRESET
        ]

    @property
    @override
    def is_on(self) -> bool:
        """Return true if the entity is on."""
        return bool(self.coordinator.data.state.power_switch)

    @property
    @override
    def oscillating(self) -> bool:
        """Return whether or not the fan is currently oscillating."""
        return bool(self.coordinator.data.state.oscillating_switch)

    @property
    @override
    def percentage(self) -> int:
        """Return the current speed as a percentage."""
        try:
            return ordered_list_item_to_percentage(
                self._named_fan_speeds, self.coordinator.data.state.fan_speed
            )
        except ValueError:
            return 0

    def _preset_to_supported_speed(self, preset_mode: str) -> DeyeFanSpeed:
        """Map a preset to a fan speed advertised by this model."""
        if preset_mode not in (self._attr_preset_modes or []):
            raise ValueError(f"Unsupported preset mode: {preset_mode}")
        return preset_mode_to_deye_fan_speed(preset_mode)

    @property
    @override
    def preset_mode(self) -> str | None:
        """Return the current named fan speed preset."""
        preset = deye_fan_speed_to_preset_mode(self.coordinator.data.state.fan_speed)
        if preset is None or preset not in (self._attr_preset_modes or []):
            return None
        return preset

    @override
    async def async_oscillate(self, oscillating: bool) -> None:
        """Oscillate the fan."""
        self.coordinator.data.state.oscillating_switch = oscillating
        await self.publish_command_from_current_state()

    @override
    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if percentage == 0:
            await self.async_turn_off()
            return
        fan_speed = DeyeFanSpeed(
            percentage_to_ordered_list_item(self._named_fan_speeds, percentage)
        )
        self.coordinator.data.state.fan_speed = fan_speed
        await self.publish_command_from_current_state()

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the fan speed from a named preset."""
        self.coordinator.data.state.fan_speed = self._preset_to_supported_speed(
            preset_mode
        )
        await self.publish_command_from_current_state()

    @override
    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        self.coordinator.data.state.power_switch = True
        if preset_mode is not None:
            self.coordinator.data.state.fan_speed = self._preset_to_supported_speed(
                preset_mode
            )
        elif percentage is not None:
            fan_speed = DeyeFanSpeed(
                percentage_to_ordered_list_item(self._named_fan_speeds, percentage)
            )
            self.coordinator.data.state.fan_speed = fan_speed
        await self.publish_command_from_current_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.coordinator.data.state.power_switch = False
        await self.publish_command_from_current_state()
