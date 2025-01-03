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
from libdeye.cloud_api import DeyeCloudApi
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo, DeyeFanSpeed
from libdeye.utils import get_product_feature_config

from . import DeyeEntity
from .const import (
    DATA_CLOUD_API,
    DATA_COORDINATOR,
    DATA_DEVICE_LIST,
    DATA_MQTT_CLIENT,
    DOMAIN,
)
from .data_coordinator import DeyeDataUpdateCoordinator


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
            async_add_entities(
                [
                    DeyeFan(
                        data[DATA_COORDINATOR][device["device_id"]],
                        device,
                        data[DATA_MQTT_CLIENT],
                        data[DATA_CLOUD_API],
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
        mqtt_client: DeyeMqttClient,
        cloud_api: DeyeCloudApi,
    ) -> None:
        """Initialize the fan entity."""
        super().__init__(coordinator, device, mqtt_client, cloud_api)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-fan"
        self.entity_id = f"fan.{self.entity_id_base}_fan"
        feature_config = get_product_feature_config(device["product_id"])
        self._attr_supported_features = FanEntityFeature.SET_SPEED
        if hasattr(FanEntityFeature, "TURN_ON"):  # v2024.8
            self._attr_supported_features |= FanEntityFeature.TURN_ON
        if hasattr(FanEntityFeature, "TURN_OFF"):
            self._attr_supported_features |= FanEntityFeature.TURN_OFF
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
        await self.publish_command_async("oscillating_switch", oscillating)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if percentage == 0:
            await self.async_turn_off()
        fan_speed = DeyeFanSpeed(
            percentage_to_ordered_list_item(self._named_fan_speeds, percentage)
        )
        self.device_state.fan_speed = fan_speed
        await self.publish_command_async("fan_speed", fan_speed)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        self.device_state.power_switch = True
        await self.publish_command_async("power_switch", True)
        if percentage is not None:
            fan_speed = DeyeFanSpeed(
                percentage_to_ordered_list_item(self._named_fan_speeds, percentage)
            )
            self.device_state.fan_speed = fan_speed
            await self.publish_command_async("fan_speed", fan_speed)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.device_state.power_switch = False
        await self.publish_command_async("power_switch", False)
