"""Platform for humidifier integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.components.humidifier.const import MODE_AUTO, MODE_SLEEP
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from libdeye.cloud_api import DeyeCloudApi
from libdeye.device_state_command import DeyeDeviceState
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo, DeyeDeviceMode
from libdeye.utils import get_product_feature_config

from . import DeyeEntity
from .const import DATA_CLOUD_API, DATA_DEVICE_LIST, DATA_MQTT_CLIENT, DOMAIN

MODE_MANUAL = "manual"
MODE_AIR_PURIFIER = "air_purifier"
MODE_CLOTHES_DRYER = "clothes_dryer"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add dehumidifiers for passed config_entry in HA."""
    data = hass.data[DOMAIN][config_entry.entry_id]

    for device in data[DATA_DEVICE_LIST]:
        deye_dehumidifier = DeyeDehumidifier(
            device, data[DATA_MQTT_CLIENT], data[DATA_CLOUD_API]
        )
        async_add_entities([deye_dehumidifier])


class DeyeDehumidifier(DeyeEntity, HumidifierEntity):
    """Dehumidifier entity."""

    _attr_translation_key = "dehumidifier"
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_name = None  # Inherits from device name

    def __init__(
        self,
        device: DeyeApiResponseDeviceInfo,
        mqtt_client: DeyeMqttClient,
        cloud_api: DeyeCloudApi,
    ) -> None:
        """Initialize the humidifier entity."""
        super().__init__(device, mqtt_client, cloud_api)
        assert self._attr_unique_id is not None
        self.subscription_muted: CALLBACK_TYPE | None = None
        self._attr_unique_id += "-dehumidifier"
        self.entity_id = f"humidifier.{self.entity_id_base}_dehumidifier"
        feature_config = get_product_feature_config(device["product_id"])
        if len(feature_config["mode"]) > 0:
            self._attr_supported_features = HumidifierEntityFeature.MODES
        self._attr_available_modes = list(
            map(deye_mode_to_hass_mode, feature_config["mode"])
        )
        self._attr_min_humidity = feature_config["min_target_humidity"]
        self._attr_max_humidity = feature_config["max_target_humidity"]
        self._attr_entity_picture = device["product_icon"]
        self.data_change_list: dict = dict()

    async def call_method(self, event):
        if event.data.get("device_id") == self._device["device_id"]:
            prop = event.data.get("prop")
            value = event.data.get("value")
            await self.publish_command(prop, value)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.hass.helpers.event.async_track_time_interval(
            self.put_device_state, timedelta(seconds=5)
        )
        self.hass.bus.async_listen("call_humidifier_method", self.call_method)

    @callback
    async def put_device_state(self, now: datetime | None = None) -> None:
        if len(self.data_change_list.items()) > 0:
            command = self.device_state.to_command()
            for prop, value in self.data_change_list.items():
                set_class_variable(command, prop, value)
            self.data_change_list.clear()
            if self._device["platform"] == 1:
                """Publish a MQTT command to this device."""
                self._mqtt_client.publish_command(
                    self._device["product_id"],
                    self._device["device_id"],
                    command.bytes(),
                )
            elif self._device["platform"] == 2:
                """Post a Remote command to this device."""
                await self._cloud_api.set_fog_platform_device_properties(
                    self._device["device_id"], command.json()
                )

            self.async_write_ha_state()

    async def publish_command(self, prop, value) -> None:
        self.data_change_list[prop] = value

    @property
    def get_device_state(self) -> DeyeDeviceState:
        return self.device_state

    @property
    def target_humidity(self) -> int:
        """Return the humidity we try to reach."""
        return self.device_state.target_humidity

    @property
    def current_humidity(self) -> int:
        """Return the current humidity."""
        return self.device_state.environment_humidity

    @property
    def is_on(self) -> bool:
        """Return True if device is on."""
        return self.device_state.power_switch

    @property
    def mode(self) -> str:
        """Return the working mode."""
        return deye_mode_to_hass_mode(self.device_state.mode)

    @property
    def action(self) -> str:
        """
        Return the current action.

        off/drying/idle are from `homeassistant.components.humidifier.const.HumidifierAction`

        For backward compatibility, we cannot directly import them from homeassistant (which requires
        homeassistant >= 2023.7)
        """
        if not self.device_state.power_switch:
            return "off"
        elif self.device_state.fan_running:
            return "drying"
        else:
            return "idle"

    async def async_set_mode(self, mode: str) -> None:
        """Set new working mode."""
        self.device_state.mode = hass_mode_to_deye_mode(mode)
        await self.publish_command_async("mode", hass_mode_to_deye_mode(mode))

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        self.device_state.target_humidity = humidity
        await self.publish_command_async("target_humidity", humidity)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the device on."""
        self.device_state.power_switch = True
        await self.publish_command_async("power_switch", True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the device off."""
        self.device_state.power_switch = False
        await self.publish_command_async("power_switch", False)


def set_class_variable(obj, var_name, new_value):
    if hasattr(obj, var_name):
        setattr(obj, var_name, new_value)
    else:
        raise AttributeError(
            f"'{obj.__class__.__name__}' object has no attribute '{var_name}'"
        )


def deye_mode_to_hass_mode(mode: DeyeDeviceMode) -> str:
    """Map DeyeDeviceMode to HumidifierEntity mode."""
    if mode == DeyeDeviceMode.CLOTHES_DRYER_MODE:
        return MODE_CLOTHES_DRYER
    if mode == DeyeDeviceMode.AIR_PURIFIER_MODE:
        return MODE_AIR_PURIFIER
    if mode == DeyeDeviceMode.AUTO_MODE:
        return MODE_AUTO
    if mode == DeyeDeviceMode.SLEEP_MODE:
        return MODE_SLEEP
    return MODE_MANUAL


def hass_mode_to_deye_mode(mode: str) -> DeyeDeviceMode:
    """Map HumidifierEntity mode to DeyeDeviceMode."""
    if mode == MODE_CLOTHES_DRYER:
        return DeyeDeviceMode.CLOTHES_DRYER_MODE
    if mode == MODE_AIR_PURIFIER:
        return DeyeDeviceMode.AIR_PURIFIER_MODE
    if mode == MODE_AUTO:
        return DeyeDeviceMode.AUTO_MODE
    if mode == MODE_SLEEP:
        return DeyeDeviceMode.SLEEP_MODE
    return DeyeDeviceMode.MANUAL_MODE
