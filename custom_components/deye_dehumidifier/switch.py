"""Platform for humidifier integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from libdeye.cloud_api import DeyeApiResponseDeviceInfo
from libdeye.const import DeyeDeviceMode, get_product_feature_config

from . import DATA_KEY, DeyeEntity
from .data_coordinator import DeyeDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add swiches for passed config_entry in HA."""
    data = hass.data[DATA_KEY][config_entry.entry_id]

    for device in data.device_list:
        feature_config = get_product_feature_config(device["product_id"])
        async_add_entities(
            [
                DeyeChildLockSwitch(
                    data.coordinator_map[device["device_id"]],
                    device,
                )
            ]
        )
        async_add_entities(
            [
                DeyeContinuousSwitch(
                    data.coordinator_map[device["device_id"]],
                    device,
                    feature_config["min_target_humidity"],
                )
            ]
        )
        if feature_config["anion"]:
            async_add_entities(
                [
                    DeyeAnionSwitch(
                        data.coordinator_map[device["device_id"]],
                        device,
                    )
                ]
            )
        if feature_config["water_pump"]:
            async_add_entities(
                [
                    DeyeWaterPumpSwitch(
                        data.coordinator_map[device["device_id"]],
                        device,
                    )
                ]
            )


class DeyeChildLockSwitch(DeyeEntity, SwitchEntity):
    """Child lock switch entity."""

    _attr_translation_key = "child_lock"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-child-lock"
        self.entity_id = f"switch.{self.entity_id_base}_child_lock"

    @property
    def is_on(self) -> bool:
        """Return True if the child lock is on."""
        return self.coordinator.data.state.child_lock_switch

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the child lock on."""
        self.coordinator.data.state.child_lock_switch = True
        await self.publish_command_from_current_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the child lock off."""
        self.coordinator.data.state.child_lock_switch = False
        await self.publish_command_from_current_state()


class DeyeAnionSwitch(DeyeEntity, SwitchEntity):
    """Anion switch entity."""

    _attr_translation_key = "anion"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-anion"
        self.entity_id = f"switch.{self.entity_id_base}_anion"

    @property
    def is_on(self) -> bool:
        """Return True if the anion switch is on."""
        return self.coordinator.data.state.anion_switch

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the anion switch on."""
        self.coordinator.data.state.anion_switch = True
        await self.publish_command_from_current_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the anion switch off."""
        self.coordinator.data.state.anion_switch = False
        await self.publish_command_from_current_state()


class DeyeWaterPumpSwitch(DeyeEntity, SwitchEntity):
    """Water pump switch entity."""

    _attr_translation_key = "water_pump"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-water-pump"
        self.entity_id = f"switch.{self.entity_id_base}_water_pump"

    @property
    def is_on(self) -> bool:
        """Return True if the water pump switch is on."""
        return self.coordinator.data.state.water_pump_switch

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the water pump on."""
        self.coordinator.data.state.water_pump_switch = True
        await self.publish_command_from_current_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the water pump off."""
        self.coordinator.data.state.water_pump_switch = False
        await self.publish_command_from_current_state()


class DeyeContinuousSwitch(DeyeEntity, SwitchEntity):
    """Continuous switch entity."""

    _attr_translation_key = "continuous"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
        min_supported_humidity: int,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_unique_id += "-continuous"
        self.entity_id = f"switch.{self.entity_id_base}_continuous"
        self._min_supported_humidity = min_supported_humidity

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data.state.mode == DeyeDeviceMode.MANUAL_MODE
        )

    @property
    def is_on(self) -> bool:
        """Return True if the continuous switch is on."""
        return (
            self.coordinator.data.state.target_humidity <= self._min_supported_humidity
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the continuous switch on."""
        self.coordinator.data.state.target_humidity = self._min_supported_humidity
        await self.publish_command_from_current_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the continuous switch off."""
        self.coordinator.data.state.target_humidity = 50
        await self.publish_command_from_current_state()
