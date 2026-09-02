"""Tests for the dehumidifier humidifier entity."""

from libdeye.const import DeyeDeviceMode
from libdeye.device_state import DeyeDeviceState

from custom_components.deye_dehumidifier.humidifier import MODE_MANUAL, DeyeDehumidifier
from homeassistant.components.humidifier import HumidifierAction
from homeassistant.core import HomeAssistant
from tests.helpers import MOCK_DEVICE_INFO, make_coordinator


async def test_humidifier_state_from_fake_device(
    hass: HomeAssistant, fake_device_state: DeyeDeviceState
) -> None:
    """Humidifier properties reflect the fake coordinator device state."""
    fake_device_state.power_switch = True
    fake_device_state.fan_running = True
    fake_device_state.mode = DeyeDeviceMode.MANUAL_MODE
    fake_device_state.target_humidity = 45
    fake_device_state.environment_humidity = 58

    coordinator = make_coordinator(hass, fake_device_state)
    entity = DeyeDehumidifier(coordinator, MOCK_DEVICE_INFO)

    assert entity.unique_id == "AABBCCDDEEFF-dehumidifier"
    assert entity.entity_id == "humidifier.deye_aabbccddeeff_dehumidifier"
    assert entity.is_on is True
    assert entity.current_humidity == 58
    assert entity.target_humidity == 45
    assert entity.mode == MODE_MANUAL
    assert entity.action is HumidifierAction.DRYING
    assert entity.available is True


async def test_humidifier_off_action(
    hass: HomeAssistant, fake_device_state: DeyeDeviceState
) -> None:
    """A powered-off device reports the OFF action."""
    fake_device_state.power_switch = False
    coordinator = make_coordinator(hass, fake_device_state)
    entity = DeyeDehumidifier(coordinator, MOCK_DEVICE_INFO)

    assert entity.is_on is False
    assert entity.action is HumidifierAction.OFF
