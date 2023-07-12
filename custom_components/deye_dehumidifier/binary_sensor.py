"""Platform for humidifier integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo

from . import DeyeEntity
from .const import DATA_DEVICE_LIST, DATA_MQTT_CLIENT, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    data = hass.data[DOMAIN][config_entry.entry_id]

    for device in data[DATA_DEVICE_LIST]:
        async_add_entities(
            [
                DeyeWaterTankBinarySensor(device, data[DATA_MQTT_CLIENT]),
                DeyeDefrostingBinarySensor(device, data[DATA_MQTT_CLIENT]),
            ]
        )


class DeyeWaterTankBinarySensor(DeyeEntity, BinarySensorEntity):
    """Water tank binary sensor entity."""

    _attr_translation_key = "water_tank"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient
    ) -> None:
        """Initialize the sensor."""
        super().__init__(device, mqtt_client)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-water-tank"

    @property
    def is_on(self) -> bool:
        """Return true if the water tank is full."""
        return self.device_state.water_tank_full

    @property
    def icon(self) -> str:
        """Return the icon based on the water tank state."""
        return "mdi:beer" if self.device_state.water_tank_full else "mdi:beer-outline"


class DeyeDefrostingBinarySensor(DeyeEntity, BinarySensorEntity):
    """Defrosting binary entity."""

    _attr_translation_key = "defrosting"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient
    ) -> None:
        """Initialize the sensor."""
        super().__init__(device, mqtt_client)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-defrosting"

    @property
    def is_on(self) -> bool:
        """Return true if the device is defrosting."""
        return self.device_state.defrosting

    @property
    def icon(self) -> str:
        """Return the icon based on the defrosting state."""
        return (
            "mdi:snowflake-check"
            if self.device_state.fan_running
            else "mdi:snowflake-melt"
        )
