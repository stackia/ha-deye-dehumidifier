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
from libdeye.cloud_api import DeyeApiResponseDeviceInfo

from . import DATA_KEY, DeyeEntity
from .data_coordinator import DeyeDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    data = hass.data[DATA_KEY][config_entry.entry_id]
    for device in data.device_list:
        async_add_entities(
            [
                DeyeWaterTankBinarySensor(
                    data.coordinator_map[device["device_id"]],
                    device,
                ),
                DeyeDefrostingBinarySensor(
                    data.coordinator_map[device["device_id"]],
                    device,
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
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-water-tank"
        self.entity_id = f"binary_sensor.{self.entity_id_base}_water_tank"

    @property
    def is_on(self) -> bool:
        """Return true if the water tank is full."""
        return self.coordinator.data.state.water_tank_full


class DeyeDefrostingBinarySensor(DeyeEntity, BinarySensorEntity):
    """Defrosting binary entity."""

    _attr_translation_key = "defrosting"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-defrosting"
        self.entity_id = f"binary_sensor.{self.entity_id_base}_defrosting"

    @property
    def is_on(self) -> bool:
        """Return true if the device is defrosting."""
        return self.coordinator.data.state.defrosting
