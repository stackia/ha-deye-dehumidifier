"""Platform for dehumidifier switch entities."""

from typing import Any, Literal, NamedTuple, override

from libdeye.cloud_api import DeyeApiResponseDeviceInfo
from libdeye.const import DeyeDeviceMode, DeyeProductConfig, get_product_feature_config

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeyeConfigEntry, DeyeEntity, async_setup_dynamic_entities
from .data_coordinator import DeyeDataUpdateCoordinator


class _FlagSwitchSpec(NamedTuple):
    """One boolean config switch bound to a DeyeDeviceState attribute."""

    translation_key: str
    unique_suffix: str
    state_attr: str
    feature_key: (
        Literal["anion", "water_pump", "uv", "prompt_sound", "screen_display"] | None
    ) = None


# Child lock is always created. The rest follow product JSON gates, the
# same as anion (including uv / prompt_sound / screen_display). Fog JSON
# still skips null Integers, matching official sendCommand. Continuous
# dehumidify is not a device flag and stays on DeyeContinuousSwitch.
_ALWAYS_ON_FLAG_SWITCHES = (
    _FlagSwitchSpec("child_lock", "child-lock", "child_lock_switch"),
)
_FEATURE_FLAG_SWITCHES = (
    _FlagSwitchSpec("anion", "anion", "anion_switch", "anion"),
    _FlagSwitchSpec("water_pump", "water-pump", "water_pump_switch", "water_pump"),
    _FlagSwitchSpec("uv", "uv", "uv_switch", "uv"),
    _FlagSwitchSpec("prompt_sound", "prompt-sound", "prompt_sound", "prompt_sound"),
    _FlagSwitchSpec(
        "screen_display", "screen-display", "screen_display", "screen_display"
    ),
)

# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0


def _feature_flag_enabled(
    feature_config: DeyeProductConfig,
    spec: _FlagSwitchSpec,
) -> bool:
    """Return True if this product JSON advertises the switch."""
    if spec.feature_key is None:
        return True
    return bool(feature_config[spec.feature_key])


def _switch_entities(
    coordinator: DeyeDataUpdateCoordinator, device: DeyeApiResponseDeviceInfo
) -> list[SwitchEntity]:
    """Return the switch entities advertised by this product."""
    feature_config = get_product_feature_config(device["product_id"])
    entities: list[SwitchEntity] = [
        DeyeConfigSwitch(coordinator, device, spec) for spec in _ALWAYS_ON_FLAG_SWITCHES
    ]
    entities.append(
        DeyeContinuousSwitch(
            coordinator,
            device,
            feature_config["min_target_humidity"],
        )
    )
    entities.extend(
        DeyeConfigSwitch(coordinator, device, spec)
        for spec in _FEATURE_FLAG_SWITCHES
        if _feature_flag_enabled(feature_config, spec)
    )
    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeyeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add switches for this config entry."""
    async_setup_dynamic_entities(hass, entry, async_add_entities, _switch_entities)


class DeyeConfigSwitch(DeyeEntity, SwitchEntity):
    """Boolean configuration switch (child lock, anion, UV, …).

    Product JSON only gates whether the entity is created. Fog GET may
    omit the key; ``is_on`` treats that as off. Serialize skips nulls.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DeyeDataUpdateCoordinator,
        device: DeyeApiResponseDeviceInfo,
        spec: _FlagSwitchSpec,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device)
        assert self._attr_unique_id is not None
        self._attr_translation_key = spec.translation_key
        self._attr_unique_id += f"-{spec.unique_suffix}"
        self._state_attr = spec.state_attr

    @property
    @override
    def is_on(self) -> bool:
        """Return True if the switch is on."""
        return bool(getattr(self.coordinator.data.state, self._state_attr))

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        setattr(self.coordinator.data.state, self._state_attr, True)
        await self.publish_command_from_current_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        setattr(self.coordinator.data.state, self._state_attr, False)
        await self.publish_command_from_current_state()


class DeyeContinuousSwitch(DeyeEntity, SwitchEntity):
    """Continuous dehumidify, encoded as the product's minimum target humidity."""

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
        self._min_supported_humidity = min_supported_humidity

    @property
    @override
    def available(self) -> bool:
        """Return True if continuous mode can be controlled."""
        return (
            super().available
            and self.coordinator.data.state.mode == DeyeDeviceMode.MANUAL_MODE
        )

    @property
    @override
    def is_on(self) -> bool:
        """Return True if the continuous switch is on."""
        return (
            self.coordinator.data.state.target_humidity <= self._min_supported_humidity
        )

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the continuous switch on."""
        self.coordinator.data.state.target_humidity = self._min_supported_humidity
        await self.publish_command_from_current_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the continuous switch off."""
        self.coordinator.data.state.target_humidity = 50
        await self.publish_command_from_current_state()
