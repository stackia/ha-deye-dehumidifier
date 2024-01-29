"""Platform for humidifier integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo
from libdeye.utils import get_product_feature_config

from . import DeyeEntity
from .const import DATA_DEVICE_LIST, DATA_MQTT_CLIENT, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add swiches for passed config_entry in HA."""
    data = hass.data[DOMAIN][config_entry.entry_id]

    for device in data[DATA_DEVICE_LIST]:
        async_add_entities([DeyeChildLockSwitch(device, data[DATA_MQTT_CLIENT])])
        feature_config = get_product_feature_config(device["product_id"])
        if feature_config["anion"]:
            async_add_entities([DeyeAnionSwitch(device, data[DATA_MQTT_CLIENT])])
        if feature_config["water_pump"]:
            async_add_entities([DeyeWaterPumpSwitch(device, data[DATA_MQTT_CLIENT])])


class DeyeChildLockSwitch(DeyeEntity, SwitchEntity):
    """Child lock switch entity."""

    _attr_translation_key = "child_lock"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:teddy-bear"

    def __init__(
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient
    ) -> None:
        """Initialize the switch."""
        super().__init__(device, mqtt_client)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-child-lock"
        self.entity_id = f"switch.{self.entity_id_base}_child_lock"

    @property
    def is_on(self) -> bool:
        """Return True if the child lock is on."""
        return self.device_state.child_lock_switch

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the child lock on."""
        self.device_state.child_lock_switch = True
        self.publish_command(self.device_state.to_command())

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the child lock off."""
        self.device_state.child_lock_switch = False
        self.publish_command(self.device_state.to_command())


class DeyeAnionSwitch(DeyeEntity, SwitchEntity):
    """Anion switch entity."""

    _attr_translation_key = "anion"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:atom"

    def __init__(
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient
    ) -> None:
        """Initialize the switch."""
        super().__init__(device, mqtt_client)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-anion"
        self.entity_id = f"switch.{self.entity_id_base}_anion"

    @property
    def is_on(self) -> bool:
        """Return True if the anion switch is on."""
        return self.device_state.anion_switch

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the anion switch on."""
        self.device_state.anion_switch = True
        self.publish_command(self.device_state.to_command())

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the anion switch off."""
        self.device_state.anion_switch = False
        self.publish_command(self.device_state.to_command())


class DeyeWaterPumpSwitch(DeyeEntity, SwitchEntity):
    """Water pump switch entity."""

    _attr_translation_key = "water_pump"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient
    ) -> None:
        """Initialize the switch."""
        super().__init__(device, mqtt_client)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-water-pump"
        self.entity_id = f"switch.{self.entity_id_base}_water_pump"

    @property
    def is_on(self) -> bool:
        """Return True if the water pump switch is on."""
        return self.device_state.water_pump_switch

    @property
    def icon(self) -> str:
        """Return the icon based on the water pump switch state."""
        return (
            "mdi:water-pump"
            if self.device_state.water_pump_switch
            else "mdi:water-pump-off"
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the water pump on."""
        self.device_state.water_pump_switch = True
        self.publish_command(self.device_state.to_command())

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the water pump off."""
        self.device_state.water_pump_switch = False
        self.publish_command(self.device_state.to_command())
