import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from libdeye.const import QUERY_DEVICE_STATE_COMMAND
from libdeye.device_state_command import DeyeDeviceState

_LOGGER = logging.getLogger(__name__)


class DeyeDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, device, mqtt_client, cloud_api):
        super().__init__(
            hass,
            _LOGGER,
            name="deye_data_update_coordinator",
            update_method=self.poll_device_state,
            update_interval=timedelta(seconds=5),
        )
        self._mqtt_client = mqtt_client
        self._cloud_api = cloud_api
        self.subscription_muted: CALLBACK_TYPE | None = None

        self.data = DeyeDeviceState(
            "1411000000370000000000000000003C3C0000000000"  # 20°C/60%RH as the default state
        )
        self._device = device
        self.device_available = self._device["online"]
        """When entity is added to Home Assistant."""
        if self._device["platform"] == 1:
            # self._mqtt_client.subscribe_availability_change(
            #     self._device["product_id"],
            #     self._device["device_id"],
            #     self.update_device_availability,
            # )
            self._mqtt_client.subscribe_state_change(
                self._device["product_id"],
                self._device["device_id"],
                self.update_device_state,
            )

        self.receive_queue = asyncio.Queue()
        self.device_available_queue = asyncio.Queue()

    def mute_subscription_for_a_while(self) -> None:
        """Mute subscription for a while to avoid state bouncing."""
        if self.subscription_muted:
            self.subscription_muted()

        @callback
        def unmute(now: datetime) -> None:
            self.subscription_muted = None

        self.subscription_muted = async_call_later(self.hass, 20, unmute)

    def update_device_state(self, state: DeyeDeviceState) -> None:
        """Will be called when received new DeyeDeviceState."""
        self.receive_queue.put_nowait(state)
        # self.async_set_updated_data(state)

    # async def async_request_refresh(self) -> None:
    #     self.mute_subscription_for_a_while()
    #     await super().async_request_refresh()

    async def poll_device_state(self) -> DeyeDeviceState:
        """
        Some Deye devices have a very long heartbeat period. So polling is still necessary to get the latest state as
        quickly as possible.
        """
        # _LOGGER.error("poll_device_state called: " + str(self._device["product_id"]))
        if self.subscription_muted:
            return self.data

        device_list = list(
            filter(
                lambda d: d["product_type"] == "dehumidifier"
                and d["device_id"] == self._device["device_id"],
                await self._cloud_api.get_device_list(),
            )
        )
        if len(device_list) > 0:
            device = device_list[0]
            self.device_available = device["online"]

        if self._device["platform"] == 1:
            self._mqtt_client.publish_command(
                self._device["product_id"],
                self._device["device_id"],
                QUERY_DEVICE_STATE_COMMAND,
            )
            response = await asyncio.wait_for(self.receive_queue.get(), timeout=10)
            return response
        elif self._device["platform"] == 2:
            response = DeyeDeviceState(
                await self._cloud_api.get_fog_platform_device_properties(
                    self._device["device_id"]
                )
            )
            # _LOGGER.error(response.to_command().json())
            return response
