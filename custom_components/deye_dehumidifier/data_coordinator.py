"""Data update coordinator for Deye dehumidifier devices."""

from datetime import datetime, timedelta
import logging
from typing import NamedTuple, override

from libdeye.client import DeyeDevice
from libdeye.device_state import DeyeDeviceState

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class DeyeDeviceData(NamedTuple):
    """Coordinator data for a single Deye device."""

    reported_state: DeyeDeviceState
    state: DeyeDeviceState
    available: bool


class DeyeDataUpdateCoordinator(DataUpdateCoordinator[DeyeDeviceData]):
    """Coordinator that keeps a Deye device's state in sync."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        device: DeyeDevice,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{device.name} ({device.device_id})",
            update_method=self.poll_device_state,
            update_interval=timedelta(seconds=30),
            always_update=False,
        )
        self.device = device
        self.state_update_muted: CALLBACK_TYPE | None = None

    @override
    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        await self.device.ensure_connected()
        reported_state = self.device.reported_state
        self.data = DeyeDeviceData(
            reported_state=reported_state,
            state=reported_state.copy(),
            available=self.device.available,
        )
        self.device.subscribe(
            on_state=self.update_device_state,
            on_availability=self.update_device_availability,
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
            DeyeDeviceData(
                reported_state=state,
                state=state.copy(),
                available=self.data.available,
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

    async def poll_device_state(self) -> DeyeDeviceData:
        """Some Deye devices have a very long heartbeat period. So polling is still necessary."""
        if self.state_update_muted:
            return self.data

        reported_state = await self.device.request_refresh()
        if reported_state is None:
            return self.data
        return DeyeDeviceData(
            reported_state=reported_state,
            state=reported_state.copy(),
            available=self.data.available,
        )
