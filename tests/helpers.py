"""Shared test doubles and constants."""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from libdeye.cloud_api import (
    DeyeApiResponseDeviceInfo,
    DeyeIotPlatform,
    transport_for_device,
)
from libdeye.device_state import DeyeDeviceState

from custom_components.deye_dehumidifier.const import (
    CONF_AUTH_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
)

MOCK_USERNAME = "13800000000"
MOCK_PASSWORD = "secret-password"
MOCK_AUTH_TOKEN = "mock-auth-token"
MOCK_USER_ID = "user-123"

DEFAULT_STATE_HEX = "1411000000370000000000000000003C3C0000000000"

MOCK_CONFIG = {
    CONF_USERNAME: MOCK_USERNAME,
    CONF_PASSWORD: MOCK_PASSWORD,
    CONF_AUTH_TOKEN: MOCK_AUTH_TOKEN,
}

MOCK_DEVICE_INFO: DeyeApiResponseDeviceInfo = {
    "producttype_id": 1,
    "device_name": "Living Room Dehumidifier",
    "product_name": "DYD-D50A3",
    "platform": DeyeIotPlatform.Classic,
    "mac": "AABBCCDDEEFF",
    "protocol_version": "4.0",
    "gatewaytype": 0,
    "is_combo": False,
    "alias": "",
    "deviceid": "device-1",
    "product_id": "unknown-product",
    "role": 1,
    "device_id": "device-1",
    "product_icon": "https://example.invalid/icon.png",
    "online": True,
    "product_type": "dehumidifier",
    "payload": DEFAULT_STATE_HEX,
    "picture_v3": "",
    "work_time": 0,
    "user_count": 1,
}


class FakeDeyeDevice:
    """In-memory DeyeDevice stand-in that never opens MQTT or HTTP."""

    def __init__(self, info: DeyeApiResponseDeviceInfo) -> None:
        """Create a device wrapper from a device-list entry."""
        self.info = info
        self.device_id = info["device_id"]
        self.name = info["device_name"]
        self.available = bool(info.get("online", False))
        payload = info.get("payload") or DEFAULT_STATE_HEX
        self.reported_state = DeyeDeviceState(
            payload if isinstance(payload, str) else DEFAULT_STATE_HEX
        )
        self.state = self.reported_state.copy()
        self.transport = transport_for_device(info)
        self.ensure_connected = AsyncMock(return_value=MagicMock())
        self.request_refresh = AsyncMock(side_effect=self._async_request_refresh)
        self.apply = AsyncMock()
        self._on_state: Callable[[DeyeDeviceState], None] | None = None
        self._on_availability: Callable[[bool], None] | None = None
        self._unsub: Callable[[], None] = lambda: None

    async def _async_request_refresh(self) -> None:
        """Deliver the current state to the subscriber, like a healthy MQTT reply."""
        if self._on_state is not None:
            self._on_state(self.reported_state)

    def subscribe(
        self,
        on_state: Callable[[DeyeDeviceState], None] | None = None,
        on_availability: Callable[[bool], None] | None = None,
    ) -> Callable[[], None]:
        """Record callbacks; tests can invoke them directly if needed."""
        self._on_state = on_state
        self._on_availability = on_availability
        return self._unsub


def make_coordinator(
    hass: Any, state: DeyeDeviceState, *, available: bool = True
) -> MagicMock:
    """Build a coordinator mock that entities can read without a live client."""
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.config_entry = None
    coordinator.data.state = state
    coordinator.data.reported_state = state
    coordinator.data.available = available
    coordinator.device = FakeDeyeDevice(MOCK_DEVICE_INFO)
    coordinator.mute_state_update_for_a_while = MagicMock()
    coordinator.async_update_listeners = MagicMock()
    coordinator.sync_reported_state_after_publish = MagicMock()
    return coordinator
