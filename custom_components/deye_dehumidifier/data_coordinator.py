import asyncio
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

CLASSIC_QUERY_TIMEOUT = 12
CLASSIC_FAILURES_BEFORE_RELOAD = 2
CLASSIC_RELOAD_DELAY = 2


class DeyeDeviceData(NamedTuple):
    reported_state: DeyeDeviceState
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
        self._config_entry_id = config_entry.entry_id
        self._classic_query_failures = 0
        self._classic_forced_unavailable = False
        self._classic_reload_cancel: CALLBACK_TYPE | None = None
        config_entry.async_on_unload(self._cancel_classic_reload)

    async def _async_setup(self) -> None:
        """Set up the coordinator"""
        reported_state = DeyeDeviceState(
            self._device["payload"]
            or "1411000000370000000000000000003C3C0000000000"  # 20°C/60%RH as the default state
        )
        self.data = DeyeDeviceData(
            reported_state=reported_state,
            state=reported_state.copy(),
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
        was_forced_unavailable = self._classic_forced_unavailable
        if self._classic_query_failures > 0:
            _LOGGER.info(
                "Classic MQTT state updates recovered for device %s after %s "
                "consecutive failure(s)",
                self._device["device_id"],
                self._classic_query_failures,
            )
        self._classic_query_failures = 0
        self._classic_forced_unavailable = False
        self._cancel_classic_reload()

        if self.state_update_muted:
            return
        self.async_set_updated_data(
            DeyeDeviceData(
                reported_state=state,
                state=state.copy(),
                available=True if was_forced_unavailable else self.data.available,
            )
        )

    def update_device_availability(self, available: bool) -> None:
        """Will be called when received device availability change."""
        self.async_set_updated_data(
            DeyeDeviceData(
                reported_state=self.data.reported_state,
                state=self.data.state,
                available=available,
            )
        )

    def sync_reported_state_after_publish(self) -> None:
        """Align reported state with the desired state after a successful publish."""
        self.data = DeyeDeviceData(
            reported_state=self.data.state.copy(),
            state=self.data.state,
            available=self.data.available,
        )

    async def _query_classic_state(self) -> DeyeDeviceState:
        """Send a Classic query and wait for a real state response."""
        mqtt_client = self.mqtt_client
        if not isinstance(mqtt_client, DeyeClassicMqttClient):
            raise TypeError("Classic state queries require a Classic MQTT client")

        future: asyncio.Future[DeyeDeviceState] = (
            asyncio.get_running_loop().create_future()
        )

        def on_state(state: DeyeDeviceState) -> None:
            if not future.done():
                future.set_result(state)

        unsubscribe = mqtt_client.subscribe_state_change(
            self._device["product_id"],
            self._device["device_id"],
            on_state,
        )

        try:
            await mqtt_client.publish_command(
                self._device["product_id"],
                self._device["device_id"],
                QUERY_DEVICE_STATE_COMMAND_CLASSIC,
            )
            return await asyncio.wait_for(future, timeout=CLASSIC_QUERY_TIMEOUT)
        finally:
            unsubscribe()

    def _cancel_classic_reload(self) -> None:
        """Cancel a pending automatic reload."""
        if self._classic_reload_cancel is None:
            return
        self._classic_reload_cancel()
        self._classic_reload_cancel = None

    def _schedule_classic_reload(self) -> None:
        """Schedule a config-entry reload to rebuild the MQTT client."""
        if self._classic_reload_cancel is not None:
            return

        @callback
        def reload_entry(_now: datetime) -> None:
            self._classic_reload_cancel = None
            self.hass.async_create_task(
                self._async_reload_config_entry(),
                f"Reload Deye config entry {self._config_entry_id}",
            )

        self._classic_reload_cancel = async_call_later(
            self.hass, CLASSIC_RELOAD_DELAY, reload_entry
        )

    async def _async_reload_config_entry(self) -> None:
        """Reload the config entry after repeated Classic MQTT failures."""
        _LOGGER.warning(
            "Reloading Deye config entry after %s consecutive Classic MQTT state "
            "query failures for device %s",
            self._classic_query_failures,
            self._device["device_id"],
        )
        try:
            await self.hass.config_entries.async_reload(self._config_entry_id)
        except Exception:
            _LOGGER.exception(
                "Failed to reload Deye config entry after Classic MQTT state "
                "query failures"
            )

    async def poll_device_state(self) -> DeyeDeviceData:
        """
        Some Deye devices have a very long heartbeat period. So polling is still necessary.
        """
        if self.state_update_muted:
            return self.data

        if isinstance(self.mqtt_client, DeyeClassicMqttClient):
            try:
                reported_state = await self._query_classic_state()
            except TimeoutError:
                self._classic_query_failures += 1
                _LOGGER.warning(
                    "Classic MQTT state query timed out after %ss for device %s; "
                    "consecutive failures: %s/%s",
                    CLASSIC_QUERY_TIMEOUT,
                    self._device["device_id"],
                    self._classic_query_failures,
                    CLASSIC_FAILURES_BEFORE_RELOAD,
                )

                if self._classic_query_failures < CLASSIC_FAILURES_BEFORE_RELOAD:
                    return self.data

                self._classic_forced_unavailable = True
                self._schedule_classic_reload()
                return DeyeDeviceData(
                    reported_state=self.data.reported_state,
                    state=self.data.state,
                    available=False,
                )

            was_forced_unavailable = self._classic_forced_unavailable
            self._classic_query_failures = 0
            self._classic_forced_unavailable = False
            self._cancel_classic_reload()
            return DeyeDeviceData(
                reported_state=reported_state,
                state=reported_state.copy(),
                available=True if was_forced_unavailable else self.data.available,
            )

        reported_state = await self.mqtt_client.query_device_state(
            self._device["product_id"],
            self._device["device_id"],
        )
        return DeyeDeviceData(
            reported_state=reported_state,
            state=reported_state.copy(),
            available=self.data.available,
        )
