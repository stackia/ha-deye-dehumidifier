"""Tests for async_setup_entry / async_unload_entry."""

from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.deye_dehumidifier import DATA_KEY
from custom_components.deye_dehumidifier.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from tests.helpers import MOCK_CONFIG, MOCK_DEVICE_INFO, FakeDeyeDevice


async def test_setup_and_unload_entry(
    hass: HomeAssistant, mock_libdeye: tuple[MagicMock, FakeDeyeDevice]
) -> None:
    """Setup stores coordinator data; unload disconnects the mocked client."""
    client, device = mock_libdeye
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, unique_id="user-123")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    data = hass.data[DATA_KEY][entry.entry_id]
    assert data.client is client
    assert data.device_list == [MOCK_DEVICE_INFO]
    assert device.device_id in data.coordinator_map
    client.list_devices.assert_awaited_once()
    device.ensure_connected.assert_awaited()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data[DATA_KEY]
    client.disconnect.assert_called_once()
