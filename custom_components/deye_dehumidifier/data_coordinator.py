import logging
from datetime import datetime, timedelta
from typing import NamedTuple

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from libdeye.cloud_api import DeyeApiResponseDeviceInfo, DeyeCloudApi
from libdeye.const import QUERY_DEVICE_STATE_COMMAND_CLASSIC
from libdeye.device_state import DeyeDeviceState
from libdeye.mqtt_client import BaseDeyeMqttClient, DeyeClassicMqttClient

_LOGGER = logging.getLogger(__name__)


class DeyeDeviceData(NamedTuple):
    state: DeyeDeviceState
    available: bool


class DeyeDataUpdateCoordinator(DataUpdateCoordinator[DeyeDeviceData]):
    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        device: DeyeApiResponseDeviceInfo,
        mqtt_client: BaseDeyeMqttClient,
        cloud_api: DeyeCloudApi,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{device['device_name']} ({device['device_id']})",
            update_method=self.poll_device_state,
            update_interval=timedelta(seconds=30),
            always_update=False,
        )
        self.mqtt_client = mqtt_client
        self._cloud_api = cloud_api
        self.state_update_muted: CALLBACK_TYPE | None = None
        self._device = device

    async def _async_setup(self) -> None:
        """Set up the coordinator"""
        self.data = DeyeDeviceData(
            state=DeyeDeviceState(
                self._device["payload"]
                or "1411000000370000000000000000003C3C0000000000"  # 20°C/60%RH as the default state
            ),
            available=self._device["online"],
        )
        self.mqtt_client.subscribe_state_change(
            self._device["product_id"],
            self._device["device_id"],
            self.update_device_state,
        )
        self.mqtt_client.subscribe_availability_change(
            self._device["product_id"],
            self._device["device_id"],
            self.update_device_availability,
        )

    def mute_state_update_for_a_while(self) -> None:
        """Mute subscription for a while to avoid state bouncing."""
        if self.state_update_muted:
            self.state_update_muted()

        @callback
        def unmute(now: datetime) -> None:
            self.state_update_muted = None

        self.state_update_muted = async_call_later(self.hass, 10, unmute)

    def update_device_state(self, state: DeyeDeviceState) -> None:
        """Will be called when received new DeyeDeviceState."""
        if self.state_update_muted:
            return
        self.async_set_updated_data(
            DeyeDeviceData(state=state, available=self.data.available)
        )

    def update_device_availability(self, available: bool) -> None:
        """Will be called when received device availability change."""
        self.async_set_updated_data(
            DeyeDeviceData(state=self.data.state, available=available)
        )

    async def poll_device_state(self) -> DeyeDeviceData:
        """
        Some Deye devices have a very long heartbeat period. So polling is still necessary.
        """
        if self.state_update_muted:
            return self.data

        if isinstance(self.mqtt_client, DeyeClassicMqttClient):
            await self.mqtt_client.publish_command(
                self._device["product_id"],
                self._device["device_id"],
                QUERY_DEVICE_STATE_COMMAND_CLASSIC,
            )
            return self.data
        else:
            return DeyeDeviceData(
                state=await self.mqtt_client.query_device_state(
                    self._device["product_id"], self._device["device_id"]
                ),
                available=self.data.available,
            )
