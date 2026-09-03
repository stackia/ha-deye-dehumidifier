"""Data update coordinator for Deye dehumidifier devices."""

import asyncio
from datetime import datetime, timedelta
import logging
from typing import NamedTuple, override

from libdeye.client import DeyeClient, DeyeDevice
from libdeye.cloud_api import (
    DeyeApiResponseDeviceInfo,
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
    DeyeDeviceTransport,
)
from libdeye.device_state import DeyeDeviceState

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CLASSIC_QUERY_FAILURES_BEFORE_RECOVERY,
    CLASSIC_RECOVERY_DELAY,
    CLASSIC_STATE_QUERY_TIMEOUT,
    DEVICE_LIST_UPDATE_INTERVAL,
    DOMAIN,
    is_dehumidifier_product_type,
)
from .subentries import configured_device_ids

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
        self._classic_query_failures = 0
        self._poll_forced_unavailable = False
        self._classic_reload_unsub: CALLBACK_TYPE | None = None
        self._classic_poll_waiter: asyncio.Future[DeyeDeviceState] | None = None

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
        self._cancel_classic_recovery()
        waiter = self._classic_poll_waiter
        if waiter is not None and not waiter.done():
            waiter.cancel()
        self._classic_poll_waiter = None

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
        recovered = self._classic_query_failures > 0 or self._poll_forced_unavailable
        self._clear_classic_query_failure()
        waiter = self._classic_poll_waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(state)
            return
        if self.state_update_muted:
            return
        self.async_set_updated_data(
            DeyeDeviceData(
                reported_state=state,
                state=state.copy(),
                available=True if recovered else self.data.available,
            )
        )

    def update_device_availability(self, available: bool) -> None:
        """Will be called when received device availability change."""
        if self._poll_forced_unavailable and available:
            return
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

    def _clear_classic_query_failure(self) -> None:
        """Reset Classic poll-failure tracking and cancel a pending reload."""
        if self._classic_query_failures:
            _LOGGER.info(
                "Classic MQTT state updates recovered for %s after %s "
                "consecutive failure(s)",
                self.name,
                self._classic_query_failures,
            )
        self._classic_query_failures = 0
        self._poll_forced_unavailable = False
        self._cancel_classic_recovery()

    @callback
    def _cancel_classic_recovery(self) -> None:
        """Cancel a pending config-entry reload."""
        if self._classic_reload_unsub is None:
            return
        self._classic_reload_unsub()
        self._classic_reload_unsub = None

    def _schedule_classic_recovery(self) -> None:
        """Reload the config entry so the pooled MQTT client is recreated."""
        if self._classic_reload_unsub is not None or self.config_entry is None:
            return

        @callback
        def _reload(_now: datetime) -> None:
            self._classic_reload_unsub = None
            if self.config_entry is None:
                return
            entry_id = self.config_entry.entry_id
            _LOGGER.warning(
                "Reloading Deye config entry after %s consecutive Classic "
                "MQTT state query failures for %s",
                self._classic_query_failures,
                self.name,
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(entry_id),
                name=f"Reload Deye config entry {entry_id}",
            )

        self._classic_reload_unsub = async_call_later(
            self.hass, CLASSIC_RECOVERY_DELAY, _reload
        )

    def _handle_classic_query_timeout(self) -> DeyeDeviceData:
        """Keep last state once; then mark unavailable and recover."""
        self._classic_query_failures += 1
        _LOGGER.warning(
            "Classic MQTT state query for %s timed out after %ss "
            "(%s/%s consecutive failures)",
            self.name,
            CLASSIC_STATE_QUERY_TIMEOUT,
            self._classic_query_failures,
            CLASSIC_QUERY_FAILURES_BEFORE_RECOVERY,
        )
        if self._classic_query_failures < CLASSIC_QUERY_FAILURES_BEFORE_RECOVERY:
            return self.data

        self._poll_forced_unavailable = True
        self._schedule_classic_recovery()
        return DeyeDeviceData(
            reported_state=self.data.reported_state,
            state=self.data.state,
            available=False,
        )

    async def _async_query_classic_state(self) -> DeyeDeviceState:
        """Publish a Classic/Combo poll and wait for the next MQTT state."""
        waiter: asyncio.Future[DeyeDeviceState] = (
            asyncio.get_running_loop().create_future()
        )
        self._classic_poll_waiter = waiter
        try:
            await self.device.request_refresh()
            async with asyncio.timeout(CLASSIC_STATE_QUERY_TIMEOUT):
                return await waiter
        finally:
            self._classic_poll_waiter = None

    @override
    async def _async_update_data(self) -> DeyeDeviceData:
        """Poll device state. Some Deye devices have a long heartbeat period.

        Fog uses HTTP ``RealData`` poll and returns when the POST succeeds.
        Classic/Combo publish the MQTT query command and wait for the
        matching ``status/hex`` payload. A cached return is not treated as
        proof that MQTT is still working.
        """
        if self.state_update_muted:
            return self.data

        try:
            if self.device.transport is DeyeDeviceTransport.FOG:
                reported_state = await self.device.request_refresh()
            else:
                try:
                    reported_state = await self._async_query_classic_state()
                except TimeoutError:
                    return self._handle_classic_query_timeout()
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
            available=True,
        )


class DeyeDeviceListCoordinator(DataUpdateCoordinator[list[DeyeApiResponseDeviceInfo]]):
    """Periodically refresh the cloud device list and sync local devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: DeyeClient,
        coordinator_map: dict[str, DeyeDataUpdateCoordinator],
        device_list: list[DeyeApiResponseDeviceInfo],
    ) -> None:
        """Initialize the device-list coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} device list",
            update_interval=DEVICE_LIST_UPDATE_INTERVAL,
        )
        self._client = client
        self.coordinator_map = coordinator_map
        self.device_list = device_list
        self._initial_sync = True
        self._last_devices: list[DeyeDevice] = []

    @override
    async def _async_update_data(self) -> list[DeyeApiResponseDeviceInfo]:
        """Fetch the cloud device list and add or remove local devices."""
        try:
            devices = [
                device
                for device in await self._client.list_devices()
                if is_dehumidifier_product_type(device.info["product_type"])
            ]
        except DeyeCloudApiInvalidAuthError as err:
            raise ConfigEntryAuthFailed from err
        except DeyeCloudApiCannotConnectError as err:
            raise UpdateFailed("Cannot connect to Deye Cloud") from err

        self._last_devices = devices
        await self._async_sync_devices(devices)
        return list(self.device_list)

    async def async_sync_configured_devices(self) -> None:
        """Create coordinators for subentries using the last successful list."""
        if not self._last_devices:
            return
        await self._async_sync_devices(self._last_devices)

    def mark_initial_sync_done(self) -> None:
        """Treat later device-list polls as incremental discovery."""
        self._initial_sync = False

    async def _async_sync_devices(self, devices: list[DeyeDevice]) -> None:
        """Create coordinators for configured devices and drop stale ones."""
        configured = (
            configured_device_ids(self.config_entry)
            if self.config_entry is not None
            else set()
        )
        current_ids = {device.device_id for device in devices}

        for device_id in list(self.coordinator_map):
            if device_id not in current_ids:
                await self._async_remove_stale_device(device_id)
            elif device_id not in configured:
                coordinator = self.coordinator_map.pop(device_id, None)
                if coordinator is not None:
                    await coordinator.async_shutdown()

        for device in devices:
            if (
                device.device_id in configured
                and device.device_id not in self.coordinator_map
            ):
                await self._async_add_device(device)

        missing = configured - current_ids
        if missing and self._initial_sync:
            for device_id in sorted(missing):
                _LOGGER.warning(
                    "Dehumidifier %s is configured but not on the Deye account",
                    device_id,
                )

        self.device_list.clear()
        self.device_list.extend(device.info for device in devices)

    async def _async_add_device(self, device: DeyeDevice) -> None:
        """Create a coordinator for a configured dehumidifier."""
        if self.config_entry is None:
            raise UpdateFailed("Config entry is missing")
        coordinator = DeyeDataUpdateCoordinator(self.hass, self.config_entry, device)
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryAuthFailed:
            await coordinator.async_shutdown()
            raise
        except ConfigEntryNotReady:
            await coordinator.async_shutdown()
            if self._initial_sync:
                raise
            _LOGGER.exception(
                "Failed to set up newly discovered dehumidifier %s (%s)",
                device.name,
                device.device_id,
            )
            return
        self.coordinator_map[device.device_id] = coordinator
        if not self._initial_sync:
            _LOGGER.info(
                "Discovered dehumidifier %s (%s)", device.name, device.device_id
            )

    async def _async_remove_stale_device(self, device_id: str) -> None:
        """Remove a dehumidifier that is no longer on the Deye account."""
        coordinator = self.coordinator_map.pop(device_id, None)
        mac: str | None = None
        if coordinator is not None:
            mac = coordinator.device.info["mac"]
            await coordinator.async_shutdown()
        else:
            for info in self.device_list:
                if info["device_id"] == device_id:
                    mac = info["mac"]
                    break
        if mac is None or self.config_entry is None:
            return

        device_registry = dr.async_get(self.hass)
        get_by_identifier = getattr(
            device_registry, "async_get_device_by_identifier", None
        )
        if callable(get_by_identifier):
            device_entry = get_by_identifier((DOMAIN, mac), self.config_entry.entry_id)
        else:
            device_entry = device_registry.async_get_device(identifiers={(DOMAIN, mac)})
        if device_entry is not None:
            device_registry.async_remove_device(device_entry.id)
            _LOGGER.info("Removed stale dehumidifier %s (%s)", mac, device_id)
