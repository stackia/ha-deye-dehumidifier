"""Tests for the Deye data coordinator."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from deye_dehumidifier.data_coordinator import (
    CLASSIC_FAILURES_BEFORE_RELOAD,
    DeyeDataUpdateCoordinator,
    DeyeDeviceData,
)
from libdeye.device_state import DeyeDeviceState
from libdeye.mqtt_client import DeyeClassicMqttClient

TEST_STATE = "14118100113B00000000000000000040300000000000"


class TestDeyeDataUpdateCoordinator(unittest.IsolatedAsyncioTestCase):
    """Test Classic MQTT polling and recovery."""

    def make_coordinator(self) -> DeyeDataUpdateCoordinator:
        """Create a coordinator without invoking Home Assistant setup."""
        coordinator = object.__new__(DeyeDataUpdateCoordinator)
        coordinator.mqtt_client = object.__new__(DeyeClassicMqttClient)
        coordinator._device = {
            "product_id": "product123",
            "device_id": "device456",
        }
        state = DeyeDeviceState(TEST_STATE)
        coordinator.data = DeyeDeviceData(state, state.copy(), True)
        coordinator.state_update_muted = None
        coordinator._classic_query_failures = 0
        coordinator._classic_forced_unavailable = False
        coordinator._classic_reload_cancel = None
        return coordinator

    async def test_query_waits_for_state_and_unsubscribes(self) -> None:
        """A Classic query returns its real response and cleans up its callback."""
        coordinator = self.make_coordinator()
        state = DeyeDeviceState(TEST_STATE)
        unsubscribe = MagicMock()
        callback = None

        def subscribe(_product_id, _device_id, state_callback):
            nonlocal callback
            callback = state_callback
            return unsubscribe

        async def publish(_product_id, _device_id, _command):
            callback(state)

        coordinator.mqtt_client.subscribe_state_change = MagicMock(
            side_effect=subscribe
        )
        coordinator.mqtt_client.publish_command = AsyncMock(side_effect=publish)

        result = await coordinator._query_classic_state()

        self.assertIs(result, state)
        unsubscribe.assert_called_once_with()

    async def test_query_timeout_unsubscribes(self) -> None:
        """A timed-out Classic query still cleans up its callback."""
        coordinator = self.make_coordinator()
        unsubscribe = MagicMock()
        coordinator.mqtt_client.subscribe_state_change = MagicMock(
            return_value=unsubscribe
        )
        coordinator.mqtt_client.publish_command = AsyncMock()

        with patch(
            "deye_dehumidifier.data_coordinator.asyncio.wait_for",
            AsyncMock(side_effect=TimeoutError),
        ):
            with self.assertRaises(TimeoutError):
                await coordinator._query_classic_state()

        unsubscribe.assert_called_once_with()

    async def test_repeated_timeouts_schedule_reload(self) -> None:
        """Only repeated Classic query failures trigger automatic recovery."""
        coordinator = self.make_coordinator()
        coordinator._query_classic_state = AsyncMock(side_effect=TimeoutError)
        coordinator._schedule_classic_reload = MagicMock()

        first_result = await coordinator.poll_device_state()
        self.assertTrue(first_result.available)
        coordinator._schedule_classic_reload.assert_not_called()

        second_result = await coordinator.poll_device_state()
        self.assertEqual(
            coordinator._classic_query_failures,
            CLASSIC_FAILURES_BEFORE_RELOAD,
        )
        self.assertFalse(second_result.available)
        coordinator._schedule_classic_reload.assert_called_once_with()

    async def test_success_restores_watchdog_availability(self) -> None:
        """A real state response cancels recovery and clears watchdog state."""
        coordinator = self.make_coordinator()
        state = DeyeDeviceState(TEST_STATE)
        coordinator.data = DeyeDeviceData(state, state.copy(), False)
        coordinator._classic_query_failures = CLASSIC_FAILURES_BEFORE_RELOAD
        coordinator._classic_forced_unavailable = True
        coordinator._query_classic_state = AsyncMock(return_value=state)
        coordinator._cancel_classic_reload = MagicMock()

        result = await coordinator.poll_device_state()

        self.assertTrue(result.available)
        self.assertEqual(coordinator._classic_query_failures, 0)
        self.assertFalse(coordinator._classic_forced_unavailable)
        coordinator._cancel_classic_reload.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
