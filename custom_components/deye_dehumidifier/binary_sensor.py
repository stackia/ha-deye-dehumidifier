"""Platform for dehumidifier binary sensors."""

from typing import override

from libdeye.cloud_api import DeyeApiResponseDeviceInfo

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeyeConfigEntry, DeyeEntity, async_setup_dynamic_entities
from .data_coordinator import DeyeDataUpdateCoordinator

# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeyeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add binary sensors for this config entry."""
    async_setup_dynamic_entities(
        hass,
        entry,
        async_add_entities,
        lambda coordinator, device: [
            DeyeWaterTankBinarySensor(coordinator, device),
            DeyeDefrostingBinarySensor(coordinator, device),
        ],
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

    @property
    @override
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

    @property
    @override
    def is_on(self) -> bool:
        """Return true if the device is defrosting."""
        return self.coordinator.data.state.defrosting
