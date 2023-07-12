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
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo, DeyeFanSpeed
from libdeye.utils import get_product_feature_config

from . import DeyeEntity
from .const import DATA_DEVICE_LIST, DATA_MQTT_CLIENT, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add fans for passed config_entry in HA."""
    data = hass.data[DOMAIN][config_entry.entry_id]

    for device in data[DATA_DEVICE_LIST]:
        feature_config = get_product_feature_config(device["product_id"])
        if len(feature_config["fan_speed"]) > 0:
            async_add_entities([DeyeFan(device, data[DATA_MQTT_CLIENT])])


class DeyeFan(DeyeEntity, FanEntity):
    """This will be provided in addition to the DeyeDehumidifier entity (only for models that supports fan control)."""

    _attr_translation_key = "fan"

    def __init__(
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient
    ) -> None:
        """Initialize the fan entity."""
        super().__init__(device, mqtt_client)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-fan"
        self.entity_id = f"fan.{self.entity_id_base}_fan"
        feature_config = get_product_feature_config(device["product_id"])
        self._attr_supported_features = FanEntityFeature.SET_SPEED
        if feature_config["oscillating"]:
            self._attr_supported_features |= FanEntityFeature.OSCILLATE
        self._named_fan_speeds = feature_config["fan_speed"]
        self._attr_speed_count = len(self._named_fan_speeds)

    @property
    def is_on(self) -> bool:
        """Return true if the entity is on."""
        return self.device_state.power_switch

    @property
    def oscillating(self) -> bool:
        """Return whether or not the fan is currently oscillating."""
        return self.device_state.oscillating_switch

    @property
    def percentage(self) -> int:
        """Return the current speed as a percentage."""
        if self.device_state.fan_speed == DeyeFanSpeed.STOPPED:
            return 0
        return ordered_list_item_to_percentage(
            self._named_fan_speeds, self.device_state.fan_speed
        )

    async def async_oscillate(self, oscillating: bool) -> None:
        """Oscillate the fan."""
        self.device_state.oscillating_switch = oscillating
        self.publish_command(self.device_state.to_command())

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if percentage == 0:
            await self.async_turn_off()
        self.device_state.fan_speed = percentage_to_ordered_list_item(
            self._named_fan_speeds, percentage
        )
        self.publish_command(self.device_state.to_command())

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        self.device_state.power_switch = True
        if percentage is not None:
            self.device_state.fan_speed = percentage_to_ordered_list_item(
                self._named_fan_speeds, percentage
            )
        self.publish_command(self.device_state.to_command())

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.device_state.power_switch = False
        self.publish_command(self.device_state.to_command())
