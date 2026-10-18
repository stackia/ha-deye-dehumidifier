"""Tests for recovery after device online/offline notifications are missed."""

from collections.abc import AsyncGenerator
from typing import cast
from unittest.mock import MagicMock

from libdeye.cloud_api import DeyeApiResponseDeviceInfo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.deye_dehumidifier import ConfigEntryData
from custom_components.deye_dehumidifier.const import DOMAIN
from custom_components.deye_dehumidifier.sensor import DeyeHumiditySensor
from homeassistant.core import HomeAssistant
from tests.helpers import MOCK_CONFIG, MOCK_DEVICE_INFO, FakeDeyeDevice


@pytest.fixture
async def offline_device_entry(
    hass: HomeAssistant, mock_libdeye: tuple[MagicMock, FakeDeyeDevice]
) -> AsyncGenerator[ConfigEntryData]:
    """Set up an offline device with real coordinators and mocked transports."""
    _, device = mock_libdeye
    device.info = MOCK_DEVICE_INFO | {"online": False}
    device.available = False
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        unique_id="user-123",
        version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    yield entry.runtime_data

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("muted", [False, True])
async def test_state_message_recovers_missing_online_notification(
    offline_device_entry: ConfigEntryData,
    mock_libdeye: tuple[MagicMock, FakeDeyeDevice],
    muted: bool,
) -> None:
    """A state message restores availability even during command-state muting."""
    _, device = mock_libdeye
    coordinator = offline_device_entry.coordinator_map[device.device_id]
    sensor = DeyeHumiditySensor(coordinator, device.info)
    reported = coordinator.data.reported_state
    desired = coordinator.data.state
    if muted:
        coordinator.state_update_muted = MagicMock()
    state = reported.copy()
    state.environment_humidity = 63

    assert not sensor.available
    assert device._on_state is not None
    device._on_state(state)

    assert sensor.available
    assert device.available
    if muted:
        assert coordinator.data.reported_state is reported
        assert coordinator.data.state is desired
    else:
        assert coordinator.data.reported_state is state
        assert sensor.native_value == 63


@pytest.mark.parametrize(("initial", "online"), [(False, True), (True, False)])
async def test_cloud_list_reconciles_missing_availability_notification(
    offline_device_entry: ConfigEntryData,
    mock_libdeye: tuple[MagicMock, FakeDeyeDevice],
    initial: bool,
    online: bool,
) -> None:
    """Periodic cloud lists repair both missed online and offline events."""
    client, device = mock_libdeye
    coordinator = offline_device_entry.coordinator_map[device.device_id]
    assert device._on_availability is not None
    device._on_availability(initial)
    state_callback = device._on_state
    availability_callback = device._on_availability
    refreshed_device = FakeDeyeDevice(device.info | {"online": online})
    client.list_devices.return_value = [refreshed_device]

    await offline_device_entry.device_list_coordinator.async_refresh()

    assert coordinator.data.available is online
    assert device.available is online
    assert coordinator.device is device
    assert device._on_state is state_callback
    assert device._on_availability is availability_callback


async def test_cloud_list_preserves_fresher_state_and_pending_command(
    offline_device_entry: ConfigEntryData,
    mock_libdeye: tuple[MagicMock, FakeDeyeDevice],
) -> None:
    """Cloud metadata refreshes keep MQTT state and the live subscribed wrapper."""
    client, device = mock_libdeye
    coordinator = offline_device_entry.coordinator_map[device.device_id]
    state = coordinator.data.reported_state.copy()
    state.environment_humidity = 63
    assert device._on_state is not None
    device._on_state(state)
    desired = coordinator.data.state
    desired.target_humidity = 45
    coordinator.state_update_muted = MagicMock()
    refreshed_device = FakeDeyeDevice(
        MOCK_DEVICE_INFO | {"device_name": "Updated name"}
    )
    client.list_devices.return_value = [refreshed_device]

    await offline_device_entry.device_list_coordinator.async_refresh()

    assert coordinator.device is device
    assert device.info["device_name"] == "Updated name"
    assert coordinator.data.reported_state is state
    assert coordinator.data.reported_state.environment_humidity == 63
    assert coordinator.data.state is desired
    assert coordinator.data.state.target_humidity == 45


@pytest.mark.parametrize("available", [False, True])
async def test_cloud_list_without_online_preserves_availability(
    offline_device_entry: ConfigEntryData,
    mock_libdeye: tuple[MagicMock, FakeDeyeDevice],
    available: bool,
) -> None:
    """An omitted cloud online field must not invent an availability change."""
    client, device = mock_libdeye
    coordinator = offline_device_entry.coordinator_map[device.device_id]
    assert device._on_availability is not None
    device._on_availability(available)
    info = {key: value for key, value in device.info.items() if key != "online"}
    refreshed_device = FakeDeyeDevice(cast(DeyeApiResponseDeviceInfo, info))
    client.list_devices.return_value = [refreshed_device]

    await offline_device_entry.device_list_coordinator.async_refresh()

    assert coordinator.data.available is available
    assert device.available is available


async def test_repeated_offline_online_cycles(
    offline_device_entry: ConfigEntryData,
    mock_libdeye: tuple[MagicMock, FakeDeyeDevice],
) -> None:
    """Repeated device reconnects recover without replacing MQTT callbacks."""
    client, device = mock_libdeye
    coordinator = offline_device_entry.coordinator_map[device.device_id]
    state_callback = device._on_state
    assert state_callback is not None

    for _ in range(3):
        client.list_devices.return_value = [
            FakeDeyeDevice(device.info | {"online": False})
        ]
        await offline_device_entry.device_list_coordinator.async_refresh()
        assert not coordinator.data.available

        state_callback(coordinator.data.reported_state.copy())
        assert coordinator.data.available
        assert device.available
        assert coordinator.device is device
        assert device._on_state is state_callback
