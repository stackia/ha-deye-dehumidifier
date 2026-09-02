"""Tests for humidity and temperature sensors."""

from libdeye.device_state import DeyeDeviceState

from custom_components.deye_dehumidifier.sensor import (
    DeyeHumiditySensor,
    DeyeTemperatureSensor,
)
from homeassistant.core import HomeAssistant
from tests.helpers import MOCK_DEVICE_INFO, make_coordinator


async def test_sensor_state_from_fake_device(
    hass: HomeAssistant, fake_device_state: DeyeDeviceState
) -> None:
    """Sensors expose environment humidity and temperature from coordinator data."""
    fake_device_state.environment_humidity = 62
    fake_device_state.environment_temperature = 23

    coordinator = make_coordinator(hass, fake_device_state)
    humidity = DeyeHumiditySensor(coordinator, MOCK_DEVICE_INFO)
    temperature = DeyeTemperatureSensor(coordinator, MOCK_DEVICE_INFO)

    assert humidity.unique_id == "AABBCCDDEEFF-humidity"
    assert humidity.native_value == 62
    assert humidity.available is True

    assert temperature.unique_id == "AABBCCDDEEFF-temperature"
    assert temperature.native_value == 23
    assert temperature.available is True
