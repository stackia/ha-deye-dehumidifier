"""Platform for humidifier integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)
from libdeye.cloud_api import DeyeApiResponseDeviceInfo
from libdeye.const import DeyeFanSpeed, get_product_feature_config

from . import DATA_KEY, DeyeEntity
from .data_coordinator import DeyeDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add fans for passed config_entry in HA."""
    data = hass.data[DATA_KEY][config_entry.entry_id]
    for device in data.device_list:
        feature_config = get_product_feature_config(device["product_id"])
        if len(feature_config["fan_speed"]) > 0:
            async_add_entities(
                [
                    DeyeFan(
                        data.coordinator_map[device["device_id"]],
                        device,
                    )
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
        self.entity_id = f"fan.{self.entity_id_base}_fan"
        feature_config = get_product_feature_config(device["product_id"])
        self._attr_supported_features = (
            FanEntityFeature.SET_SPEED
            | FanEntityFeature.TURN_ON
            | FanEntityFeature.TURN_OFF
        )
        if feature_config["oscillating"]:
            self._attr_supported_features |= FanEntityFeature.OSCILLATE
        self._named_fan_speeds = feature_config["fan_speed"]
        self._attr_speed_count = len(self._named_fan_speeds)

    @property
    def is_on(self) -> bool:
        """Return true if the entity is on."""
        return self.coordinator.data.state.power_switch

    @property
    def oscillating(self) -> bool:
        """Return whether or not the fan is currently oscillating."""
        return self.coordinator.data.state.oscillating_switch

    @property
    def percentage(self) -> int:
        """Return the current speed as a percentage."""
        try:
            return ordered_list_item_to_percentage(
                self._named_fan_speeds, self.coordinator.data.state.fan_speed
            )
        except ValueError:
            return 0

    async def async_oscillate(self, oscillating: bool) -> None:
        """Oscillate the fan."""
        self.coordinator.data.state.oscillating_switch = oscillating
        await self.publish_command_from_current_state()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if percentage == 0:
            await self.async_turn_off()
        fan_speed = DeyeFanSpeed(
            percentage_to_ordered_list_item(self._named_fan_speeds, percentage)
        )
        self.coordinator.data.state.fan_speed = fan_speed
        await self.publish_command_from_current_state()

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        self.coordinator.data.state.power_switch = True
        if percentage is not None:
            fan_speed = DeyeFanSpeed(
                percentage_to_ordered_list_item(self._named_fan_speeds, percentage)
            )
            self.coordinator.data.state.fan_speed = fan_speed
        await self.publish_command_from_current_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.coordinator.data.state.power_switch = False
        await self.publish_command_from_current_state()
