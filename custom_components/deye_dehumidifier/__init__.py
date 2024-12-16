"""The Deye Dehumidifier integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, STATE_ON
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from libdeye.cloud_api import (
    DeyeCloudApi,
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)

from libdeye.device_state_command import DeyeDeviceCommand, DeyeDeviceState
from libdeye.mqtt_client import DeyeMqttClient
from libdeye.types import DeyeApiResponseDeviceInfo, DeyeFanSpeed, DeyeDeviceMode
from .data_coordinator import DeyeDataUpdateCoordinator
from .const import (
    CONF_AUTH_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    DATA_CLOUD_API,
    DATA_DEVICE_LIST,
    DATA_MQTT_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    MANUFACTURER,
)

PLATFORMS: list[Platform] = [
    Platform.HUMIDIFIER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.FAN,
]

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Deye Dehumidifier from a config entry."""

    def on_auth_token_refreshed(auth_token: str) -> None:
        hass.config_entries.async_update_entry(
            entry, data=entry.data | {CONF_AUTH_TOKEN: auth_token}
        )

    try:
        cloud_api = DeyeCloudApi(
            async_get_clientsession(hass),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            entry.data[CONF_AUTH_TOKEN],
        )
        cloud_api.on_auth_token_refreshed = on_auth_token_refreshed
        mqtt_info = await cloud_api.get_deye_platform_mqtt_info()
        mqtt_client = DeyeMqttClient(
            mqtt_info["mqtthost"],
            mqtt_info["sslport"],
            mqtt_info["loginname"],
            mqtt_info["password"],
            mqtt_info["endpoint"],
        )
        mqtt_client.connect()
        device_list = list(
            filter(
                lambda d: d["product_type"] == "dehumidifier",
                await cloud_api.get_device_list(),
            )
        )
        for device in device_list:
            coordinator = DeyeDataUpdateCoordinator(hass, device, mqtt_client, cloud_api)
            device[DATA_COORDINATOR] = coordinator
            await device[DATA_COORDINATOR].async_config_entry_first_refresh()

    except DeyeCloudApiInvalidAuthError as err:
        raise ConfigEntryAuthFailed from err
    except DeyeCloudApiCannotConnectError as err:
        raise ConfigEntryNotReady from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLOUD_API: cloud_api,
        DATA_MQTT_CLIENT: mqtt_client,
        DATA_DEVICE_LIST: device_list,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        mqtt_client: DeyeMqttClient = data[DATA_MQTT_CLIENT]
        mqtt_client.disconnect()

    return unload_ok


class DeyeEntity(CoordinatorEntity, Entity):
    """Initiate Deye Base Class."""

    def __init__(
        self, device: DeyeApiResponseDeviceInfo, mqtt_client: DeyeMqttClient, cloud_api: DeyeCloudApi
    ) -> None:
        # async def state_changed_listener(entity_id, old_state, new_state):
        #     _LOGGER.error(entity_id)
        #     _LOGGER.error(old_state)
        #     _LOGGER.error(new_state)
        #     if entity_id.endswith("_child_lock"):
        #         self.device_state.child_lock_switch = new_state.state is STATE_ON
        #     elif entity_id.endswith("_anion"):
        #         self.device_state.anion_switch = new_state.state is STATE_ON
        #     command = self.device_state.to_command()
        #     _LOGGER.error("old2" + json.dumps(command.json()))
        #     if self._device["platform"] == 1:
        #         """Publish a MQTT command to this device."""
        #         self._mqtt_client.publish_command(
        #             self._device["product_id"], self._device["device_id"], command.bytes()
        #         )
        #     elif self._device["platform"] == 2:
        #         """Post a Remote command to this device."""
        #         await self._cloud_api.set_fog_platform_device_properties(self._device["device_id"], command.json())
        #     # 更新设备实体的状态
        #     # self.async_schedule_update_ha_state(True)

        """Initialize the instance."""
        self.coordinator = device[DATA_COORDINATOR]
        super().__init__(self.coordinator)
        self._device = device
        self._mqtt_client = mqtt_client
        self._cloud_api = cloud_api
        self._attr_has_entity_name = True
        self._attr_available = self._device["online"]
        self._attr_unique_id = self._device["mac"]
        self.entity_id_base = f'deye_{self._device["mac"].lower()}'  # We will override HA generated entity ID
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device["mac"])},
            model=self._device["product_name"],
            manufacturer=MANUFACTURER,
            name=self._device["device_name"],
        )
        self._attr_should_poll = False
        self.subscription_muted: CALLBACK_TYPE | None = None
        # payload from the server sometimes are not a valid string
        if isinstance(self._device["payload"], str):
            self.device_state = DeyeDeviceState(self._device["payload"])
        else:
            self.device_state = DeyeDeviceState(
                "1411000000370000000000000000003C3C0000000000"  # 20°C/60%RH as the default state
            )
        remove_handle = self.coordinator.async_add_listener(self._handle_coordinator_update)
        self.async_on_remove(remove_handle)

    async def publish_command_async(self, attribute, value):
        """获取所有实体的状态。"""
        self.async_write_ha_state()
        self.hass.bus.fire('call_humidifier_method', {'prop': attribute, 'value': value})
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.device_state = self.coordinator.data
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        pass
        # if self._device["platform"] == 1:
        #     self.async_on_remove(
        #         self._mqtt_client.subscribe_availability_change(
        #             self._device["product_id"],
        #             self._device["device_id"],
        #             self.update_device_availability,
        #         )
        #     )
        #     self.async_on_remove(
        #         self._mqtt_client.subscribe_state_change(
        #             self._device["product_id"],
        #             self._device["device_id"],
        #             self.update_device_state,
        #         )
        #     )
        #
        # await self.poll_device_state()
        # self.hass.bus.async_fire('humidifier_state_changed', {'state': json.dumps(self.device_state.__dict__)})
        # self.hass.helpers.event.async_track_time_interval(
        #     self.put_device_state, timedelta(seconds=5)
        # )
        #self.async_on_remove(self.cancel_polling)

    # def update_device_availability(self, available: bool) -> None:
    #     """Will be called when received new availability status."""
    #     if self.subscription_muted:
    #         return
    #     self._attr_available = available
    #     self.async_write_ha_state()
    #
    # def update_device_state(self, state: DeyeDeviceState) -> None:
    #     """Will be called when received new DeyeDeviceState."""
    #     # if self.entity_id_base == 'deye_849dc2621ea5':
    #     #     _LOGGER.error("local:" + json.dumps(self.device_state.to_command().json()))
    #     #     _LOGGER.error("cloud:" + json.dumps(state.to_command().json()))
    #     if self.subscription_muted:
    #         return
    #     self.device_state = state
    #     self.hass.bus.async_fire('humidifier_state_changed', {'state': json.dumps(self.device_state.__dict__)})
    #     self.async_write_ha_state()

    # @callback
    # async def poll_device_state(self, now: datetime | None = None) -> None:
    #
    #     self.cancel_polling = async_call_later(self.hass, 60, self.poll_device_state)

    # def mute_subscription_for_a_while(self) -> None:
    #     """Mute subscription for a while to avoid state bouncing."""
    #     if self.hass.states.get(f"refresh.{self.entity_id_base}_dehumidifier") is False:
    #         self.subscription_muted()
    #
    #     @callback
    #     def unmute(now: datetime) -> None:
    #         self.hass.states.async_set(f"refresh.{self.entity_id_base}_dehumidifier", True)
    #
    #     self.subscription_muted = async_call_later(self.hass, 20, unmute)

    # def set_dev_state(self, state):
    #     _LOGGER.error(state)
    #     self._dev_state = state

    # def mute_command_for_a_while(self) -> None:
    #     """Mute subscription for a while to avoid state bouncing."""
    #     if self.command_muted:
    #         self.command_muted()
    #
    #     @callback
    #     def unmute(now: datetime) -> None:
    #         self.command_muted = None
    #
    #     self.command_muted = async_call_later(self.hass, 10, unmute)
    # async def publish_command(self, prop, value) -> None:
    #     self.device_state_change_list[prop] = value
        # _LOGGER.error("old" + json.dumps(self.device_state.to_command().json()))
        # set_class_variable(self.device_state, prop, value)
        # command = self.device_state.to_command()
        # _LOGGER.error("old2" + json.dumps(command.json()))
        # statatatt = self.hass.states.get(f"device.{self.entity_id_base}_state").attributes.get("state")
        # _LOGGER.error(
        #     statatatt
        # )
        # _LOGGER.error(
        #     statatatt.to_command().json()
        # )
        # _LOGGER.error(
        #     self.hass.states.get(f"fan.{self.entity_id_base}_fan").attributes
        # )



        # feature_config = get_product_feature_config(self._device["product_id"])
        # fan = self.hass.states.get(f"fan.{self.entity_id_base}_fan")
        # fan_speed = DeyeFanSpeed.STOPPED
        # oscillating_switch = False
        # if fan is not None:
        #     if len(feature_config["fan_speed"]) > 0:
        #         fan_speed = percentage_to_ordered_list_item(
        #             feature_config["fan_speed"], fan.attributes.get("percentage")
        #         )
        #     if feature_config["oscillating"]:
        #         oscillating_switch = fan.attributes.get("oscillating")
        #
        # dehumidifier = self.hass.states.get(f"humidifier.{self.entity_id_base}_dehumidifier")
        # target_humidity = 60
        # if dehumidifier is not None:
        #     if dehumidifier.attributes.get("humidity") is not None:
        #         target_humidity = dehumidifier.attributes.get("humidity")
        #
        # command = DeyeDeviceCommand(
        #     self.hass.states.is_state(f"switch.{self.entity_id_base}_anion", STATE_ON),
        #     self.hass.states.is_state(f"switch.{self.entity_id_base}_water_pump", STATE_ON),
        #     self.hass.states.is_state(f"fan.{self.entity_id_base}_fan", STATE_ON),
        #     oscillating_switch,
        #     self.hass.states.is_state(f"switch.{self.entity_id_base}_child_lock", STATE_ON),
        #     fan_speed,
        #     self.device_state.mode,
        #     target_humidity,
        # )
        # set_class_variable(command, prop, value)



        # _LOGGER.error("anion" + str())
        # _LOGGER.error("child_lock" + str(self.hass.states.get(f"{SwitchDeviceClass.SWITCH}.{self.entity_id_base}_child_lock")))
        # _LOGGER.error("muted" + str(command_muted))
        # # if command_muted:
        # #     async_call_later(self.hass, 5, self.publish_command)
        # # else:
        # _LOGGER.error("muted" + str(command_muted))
        # # command_muted = True
        # _LOGGER.error("muted" + str(command_muted))
        # _LOGGER.error(json.dumps(self.device_state.to_command().json()))
        # set_class_variable(self.device_state, prop, value)
        # command = self.device_state.to_command()
        # _LOGGER.error("new" + json.dumps(command.json()))
        # if self._device["platform"] == 1:
        #     """Publish a MQTT command to this device."""
        #     self._mqtt_client.publish_command(
        #         self._device["product_id"], self._device["device_id"], command.bytes()
        #     )
        # elif self._device["platform"] == 2:
        #     """Post a Remote command to this device."""
        #     await self._cloud_api.set_fog_platform_device_properties(self._device["device_id"], command.json())
        # self.async_write_ha_state()

        # command_muted = False
        # _LOGGER.error("muted" + str(command_muted))
