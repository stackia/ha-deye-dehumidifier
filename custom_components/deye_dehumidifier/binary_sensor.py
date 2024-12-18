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
from libdeye.cloud_api import DeyeCloudApi
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo

from . import DeyeEntity
from .const import DATA_CLOUD_API, DATA_DEVICE_LIST, DATA_MQTT_CLIENT, DOMAIN


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
                DeyeWaterTankBinarySensor(
                    device, data[DATA_MQTT_CLIENT], data[DATA_CLOUD_API]
                ),
                DeyeDefrostingBinarySensor(
                    device, data[DATA_MQTT_CLIENT], data[DATA_CLOUD_API]
                ),
            ]
        )


class DeyeWaterTankBinarySensor(DeyeEntity, BinarySensorEntity):
    """Water tank binary sensor entity."""

    _attr_translation_key = "water_tank"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        device: DeyeApiResponseDeviceInfo,
        mqtt_client: DeyeMqttClient,
        cloud_api: DeyeCloudApi,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(device, mqtt_client, cloud_api)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-water-tank"
        self.entity_id = f"binary_sensor.{self.entity_id_base}_water_tank"

    @property
    def is_on(self) -> bool:
        """Return true if the water tank is full."""
        return self.device_state.water_tank_full


class DeyeDefrostingBinarySensor(DeyeEntity, BinarySensorEntity):
    """Defrosting binary entity."""

    _attr_translation_key = "defrosting"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        device: DeyeApiResponseDeviceInfo,
        mqtt_client: DeyeMqttClient,
        cloud_api: DeyeCloudApi,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(device, mqtt_client, cloud_api)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-defrosting"
        self.entity_id = f"binary_sensor.{self.entity_id_base}_defrosting"

    @property
    def is_on(self) -> bool:
        """Return true if the device is defrosting."""
        return self.device_state.defrosting
