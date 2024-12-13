"""Platform for humidifier integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
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
                DeyeHumiditySensor(
                    device, data[DATA_MQTT_CLIENT], data[DATA_CLOUD_API]
                ),
                DeyeTemperatureSensor(
                    device, data[DATA_MQTT_CLIENT], data[DATA_CLOUD_API]
                ),
            ]
        )


class DeyeHumiditySensor(DeyeEntity, SensorEntity):
    """Humidity sensor entity."""

    _attr_translation_key = "humidity"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        device: DeyeApiResponseDeviceInfo,
        mqtt_client: DeyeMqttClient,
        cloud_api: DeyeCloudApi,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(device, mqtt_client, cloud_api)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-humidity"
        self.entity_id = f"sensor.{self.entity_id_base}_humidity"

    @property
    def native_value(self) -> int:
        """Return current environment humidity."""
        return self.device_state.environment_humidity


class DeyeTemperatureSensor(DeyeEntity, SensorEntity):
    """Temperature sensor entity."""

    _attr_translation_key = "temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        device: DeyeApiResponseDeviceInfo,
        mqtt_client: DeyeMqttClient,
        cloud_api: DeyeCloudApi,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(device, mqtt_client, cloud_api)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-temperature"
        self.entity_id = f"sensor.{self.entity_id_base}_temperature"

    @property
    def native_value(self) -> int:
        """Return current environment temperature."""
        return self.device_state.environment_temperature
