"""Platform for humidity and temperature sensors."""

from typing import override

from libdeye.cloud_api import DeyeApiResponseDeviceInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfRatio, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DATA_KEY, DeyeEntity
from .data_coordinator import DeyeDataUpdateCoordinator

# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    data = hass.data[DATA_KEY][config_entry.entry_id]
    async_add_entities(
        [
            sensor
            for device in data.device_list
            for sensor in (
                DeyeHumiditySensor(
                    data.coordinator_map[device["device_id"]],
                    device,
                ),
                DeyeTemperatureSensor(
                    data.coordinator_map[device["device_id"]],
                    device,
                ),
            )
        ]
    )


class DeyeHumiditySensor(DeyeEntity, SensorEntity):
    """Humidity sensor entity."""

    _attr_translation_key = "humidity"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-humidity"
        self.entity_id = f"sensor.{self.entity_id_base}_humidity"

    @property
    @override
    def native_value(self) -> int:
        """Return current environment humidity."""
        return self.coordinator.data.state.environment_humidity


class DeyeTemperatureSensor(DeyeEntity, SensorEntity):
    """Temperature sensor entity."""

    _attr_translation_key = "temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-temperature"
        self.entity_id = f"sensor.{self.entity_id_base}_temperature"

    @property
    @override
    def native_value(self) -> int:
        """Return current environment temperature."""
        return self.coordinator.data.state.environment_temperature
