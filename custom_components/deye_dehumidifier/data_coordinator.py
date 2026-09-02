"""Data update coordinator for Deye dehumidifier devices."""

from datetime import datetime, timedelta
import logging
from typing import NamedTuple, override

from libdeye.client import DeyeDevice
from libdeye.cloud_api import (
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)
from libdeye.device_state import DeyeDeviceState

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

_HTTP_TOO_MANY_REQUESTS = 429
_DEFAULT_RATE_LIMIT_RETRY_AFTER = 60.0


def _retry_after_from_exception(err: BaseException) -> float | None:
    """Return a backoff in seconds when a rate-limit (HTTP 429) is detected."""
    seen: set[int] = set()
    current: BaseException | None = err
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status", None)
        if status is None:
            status = getattr(current, "status_code", None)
        if status == _HTTP_TOO_MANY_REQUESTS:
            headers = getattr(current, "headers", None)
            retry_after = None
            if headers is not None:
                retry_after = headers.get("Retry-After") or headers.get("retry-after")
            if retry_after is not None:
                try:
                    return max(float(retry_after), 0.0)
                except TypeError, ValueError:
                    pass
            return _DEFAULT_RATE_LIMIT_RETRY_AFTER
        current = current.__cause__ or current.__context__
    return None


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
            update_interval=timedelta(seconds=30),
            always_update=False,
        )
        self.device = device
        self.state_update_muted: CALLBACK_TYPE | None = None
        self._unsubscribers: list[CALLBACK_TYPE] = []
        self._unavailable_logged = False

    @override
    async def _async_setup(self) -> None:
        """Set up the coordinator and subscribe to MQTT state changes."""
        await self.device.ensure_connected()
        reported_state = self.device.reported_state
        available = self.device.available
        self.data = DeyeDeviceData(
            reported_state=reported_state,
            state=reported_state.copy(),
            available=available,
        )
        self._log_availability(available)
        self._unsubscribers.append(
            self.device.subscribe(
                on_state=self.update_device_state,
                on_availability=self.update_device_availability,
            )
        )
        if self.config_entry is not None:
            self.config_entry.async_on_unload(self.unsubscribe)

    @callback
    def unsubscribe(self) -> None:
        """Remove MQTT subscriptions so callbacks do not leak after unload."""
        while self._unsubscribers:
            self._unsubscribers.pop()()
        if self.state_update_muted:
            self.state_update_muted()
            self.state_update_muted = None

    @override
    async def async_shutdown(self) -> None:
        """Unsubscribe MQTT callbacks and shut down the coordinator."""
        self.unsubscribe()
        await super().async_shutdown()

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
        self._log_availability(available)
        self.async_set_updated_data(
            DeyeDeviceData(
                reported_state=self.data.reported_state,
                state=self.data.state,
                available=available,
            )
        )

    def _log_availability(self, available: bool) -> None:
        """Log once when a device becomes unavailable, and once when it recovers."""
        if available:
            if self._unavailable_logged:
                _LOGGER.info("%s is available again", self.name)
                self._unavailable_logged = False
            return
        if not self._unavailable_logged:
            _LOGGER.info("%s is unavailable", self.name)
            self._unavailable_logged = True

    def sync_reported_state_after_publish(self) -> None:
        """Align reported state with the desired state after a successful publish."""
        self.data = DeyeDeviceData(
            reported_state=self.data.state.copy(),
            state=self.data.state,
            available=self.data.available,
        )

    @override
    async def _async_update_data(self) -> DeyeDeviceData:
        """Poll device state. Some Deye devices have a long heartbeat period.

        Fog uses HTTP ``RealData`` poll; Classic/Combo publish the MQTT query
        command. Both keep mute-window behavior and wait for MQTT for the
        next payload when ``request_refresh`` returns ``None``.
        """
        if self.state_update_muted:
            return self.data

        try:
            reported_state = await self.device.request_refresh()
        except DeyeCloudApiInvalidAuthError as err:
            raise ConfigEntryAuthFailed from err
        except (DeyeCloudApiCannotConnectError, OSError) as err:
            raise UpdateFailed(
                f"Error communicating with {self.name}: {err}",
                retry_after=_retry_after_from_exception(err),
            ) from err

        if reported_state is None:
            return self.data
        return DeyeDeviceData(
            reported_state=reported_state,
            state=reported_state.copy(),
            available=self.data.available,
        )
