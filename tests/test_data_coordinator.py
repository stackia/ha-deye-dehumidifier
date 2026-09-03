"""Tests for Classic MQTT polling and automatic recovery."""

from unittest.mock import AsyncMock, MagicMock, patch

from libdeye.cloud_api import DeyeIotPlatform
from libdeye.const import COMBO_PROTOCOL_VERSION
from libdeye.device_state import DeyeDeviceState
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.deye_dehumidifier.const import (
    CLASSIC_QUERY_FAILURES_BEFORE_RECOVERY,
    DOMAIN,
)
from custom_components.deye_dehumidifier.data_coordinator import (
    DeyeDataUpdateCoordinator,
    DeyeDeviceData,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from tests.helpers import (
    DEFAULT_STATE_HEX,
    MOCK_CONFIG,
    MOCK_DEVICE_INFO,
    FakeDeyeDevice,
)

REFRESHED_STATE_HEX = "14118100113B00000000000000000040300000000000"


def _make_coordinator(
    hass: HomeAssistant, device: FakeDeyeDevice | None = None
) -> tuple[DeyeDataUpdateCoordinator, FakeDeyeDevice]:
    """Build a coordinator with initial data, without connecting MQTT."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        unique_id="user-123",
        version=2,
    )
    entry.add_to_hass(hass)
    if device is None:
        device = FakeDeyeDevice(MOCK_DEVICE_INFO)
    coordinator = DeyeDataUpdateCoordinator(hass, entry, device)
    state = device.reported_state
    coordinator.data = DeyeDeviceData(state, state.copy(), True)
    coordinator.state_update_muted = None
    return coordinator, device


async def test_classic_poll_returns_real_state(hass: HomeAssistant) -> None:
    """Classic polling waits for the MQTT reply instead of returning the cache."""
    coordinator, device = _make_coordinator(hass)
    new_state = DeyeDeviceState(REFRESHED_STATE_HEX)

    async def _push_state() -> None:
        coordinator.update_device_state(new_state)

    device.request_refresh = AsyncMock(side_effect=_push_state)

    result = await coordinator._async_update_data()

    assert result.reported_state == new_state
    assert result.available is True
    assert coordinator._classic_query_failures == 0


async def test_classic_poll_cleans_up_waiter_after_timeout(
    hass: HomeAssistant,
) -> None:
    """A timed-out Classic poll does not leave a waiter behind."""
    coordinator, device = _make_coordinator(hass)
    device.request_refresh = AsyncMock(return_value=None)

    with patch(
        "custom_components.deye_dehumidifier.data_coordinator.CLASSIC_STATE_QUERY_TIMEOUT",
        0.01,
    ):
        result = await coordinator._async_update_data()

    assert result is coordinator.data
    assert result.available is True
    assert coordinator._classic_query_failures == 1
    assert coordinator._classic_poll_waiter is None
    assert coordinator._classic_reload_unsub is None


async def test_single_timeout_does_not_reload(hass: HomeAssistant) -> None:
    """The first Classic timeout keeps the last state and does not recover yet."""
    coordinator, device = _make_coordinator(hass)
    device.request_refresh = AsyncMock(return_value=None)
    coordinator._schedule_classic_recovery = MagicMock()

    with patch(
        "custom_components.deye_dehumidifier.data_coordinator.CLASSIC_STATE_QUERY_TIMEOUT",
        0.01,
    ):
        result = await coordinator._async_update_data()

    assert result.available is True
    coordinator._schedule_classic_recovery.assert_not_called()


async def test_repeated_timeouts_mark_unavailable_and_schedule_reload(
    hass: HomeAssistant,
) -> None:
    """A second consecutive Classic timeout marks entities unavailable."""
    coordinator, device = _make_coordinator(hass)
    device.request_refresh = AsyncMock(return_value=None)
    coordinator._classic_query_failures = CLASSIC_QUERY_FAILURES_BEFORE_RECOVERY - 1

    with patch(
        "custom_components.deye_dehumidifier.data_coordinator.CLASSIC_STATE_QUERY_TIMEOUT",
        0.01,
    ):
        result = await coordinator._async_update_data()

    assert result.available is False
    assert coordinator._poll_forced_unavailable is True
    assert coordinator._classic_query_failures == CLASSIC_QUERY_FAILURES_BEFORE_RECOVERY
    assert coordinator._classic_reload_unsub is not None
    coordinator.unsubscribe()
    assert coordinator._classic_reload_unsub is None


async def test_success_clears_failures_and_restores_availability(
    hass: HomeAssistant,
) -> None:
    """A real reply after failures restores availability and cancels recovery."""
    coordinator, device = _make_coordinator(hass)
    new_state = DeyeDeviceState(REFRESHED_STATE_HEX)
    coordinator.data = DeyeDeviceData(new_state, new_state.copy(), False)
    coordinator._classic_query_failures = CLASSIC_QUERY_FAILURES_BEFORE_RECOVERY
    coordinator._poll_forced_unavailable = True
    coordinator._classic_reload_unsub = MagicMock()

    async def _push_state() -> None:
        coordinator.update_device_state(new_state)

    device.request_refresh = AsyncMock(side_effect=_push_state)

    result = await coordinator._async_update_data()

    assert result.available is True
    assert coordinator._classic_query_failures == 0
    assert coordinator._poll_forced_unavailable is False
    assert coordinator._classic_reload_unsub is None


async def test_late_state_cancels_pending_reload(hass: HomeAssistant) -> None:
    """A late MQTT payload restores availability and cancels a pending reload."""
    coordinator, _device = _make_coordinator(hass)
    coordinator._classic_query_failures = CLASSIC_QUERY_FAILURES_BEFORE_RECOVERY
    coordinator._poll_forced_unavailable = True
    coordinator.data = DeyeDeviceData(
        coordinator.data.reported_state, coordinator.data.state, False
    )
    coordinator._schedule_classic_recovery()
    assert coordinator._classic_reload_unsub is not None

    new_state = DeyeDeviceState(REFRESHED_STATE_HEX)
    coordinator.update_device_state(new_state)

    assert coordinator._classic_query_failures == 0
    assert coordinator._poll_forced_unavailable is False
    assert coordinator._classic_reload_unsub is None
    assert coordinator.data.available is True
    assert coordinator.data.reported_state == new_state


async def test_forced_unavailable_ignores_online_until_state(
    hass: HomeAssistant,
) -> None:
    """An online topic must not clear a poll-forced unavailable state."""
    coordinator, _device = _make_coordinator(hass)
    coordinator._poll_forced_unavailable = True
    coordinator.data = DeyeDeviceData(
        coordinator.data.reported_state, coordinator.data.state, False
    )

    coordinator.update_device_availability(True)

    assert coordinator.data.available is False
    assert coordinator._poll_forced_unavailable is True


async def test_fog_poll_does_not_wait_for_mqtt(hass: HomeAssistant) -> None:
    """Fog HTTP poll success is enough; it must not wait for an MQTT payload."""
    info = {**MOCK_DEVICE_INFO, "platform": DeyeIotPlatform.Fog}
    device = FakeDeyeDevice(info)
    device.request_refresh = AsyncMock(return_value=None)
    coordinator, _ = _make_coordinator(hass, device)

    result = await coordinator._async_update_data()

    assert result is coordinator.data
    assert coordinator._classic_query_failures == 0
    device.request_refresh.assert_awaited_once()


async def test_combo_poll_waits_for_mqtt_reply(hass: HomeAssistant) -> None:
    """Combo uses Classic MQTT transport and must wait for status/hex."""
    info = {
        **MOCK_DEVICE_INFO,
        "is_combo": True,
        "protocol_version": COMBO_PROTOCOL_VERSION,
    }
    device = FakeDeyeDevice(info)
    coordinator, _ = _make_coordinator(hass, device)
    new_state = DeyeDeviceState(REFRESHED_STATE_HEX)

    async def _push_state() -> None:
        coordinator.update_device_state(new_state)

    device.request_refresh = AsyncMock(side_effect=_push_state)

    result = await coordinator._async_update_data()

    assert result.reported_state == new_state
    assert result.available is True


async def test_fog_http_timeout_raises_update_failed(hass: HomeAssistant) -> None:
    """A Fog HTTP timeout is a connection failure, not a Classic MQTT miss."""
    info = {**MOCK_DEVICE_INFO, "platform": DeyeIotPlatform.Fog}
    device = FakeDeyeDevice(info)
    device.request_refresh = AsyncMock(side_effect=TimeoutError("http"))
    coordinator, _ = _make_coordinator(hass, device)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator._classic_query_failures == 0
    assert coordinator._classic_reload_unsub is None


async def test_muted_poll_returns_cache(hass: HomeAssistant) -> None:
    """A mute window skips polling so optimistic local state is not overwritten."""
    coordinator, device = _make_coordinator(hass)
    coordinator.state_update_muted = MagicMock()
    device.request_refresh = AsyncMock()

    result = await coordinator._async_update_data()

    assert result is coordinator.data
    device.request_refresh.assert_not_called()


async def test_setup_classic_device_receives_refresh_reply(
    hass: HomeAssistant,
) -> None:
    """Full first refresh succeeds when FakeDeyeDevice echoes the current state."""
    coordinator, device = _make_coordinator(hass)
    device.reported_state = DeyeDeviceState(DEFAULT_STATE_HEX)
    await coordinator._async_setup()

    result = await coordinator._async_update_data()

    assert result.reported_state == device.reported_state
    assert result.available is True
    assert coordinator._classic_query_failures == 0
