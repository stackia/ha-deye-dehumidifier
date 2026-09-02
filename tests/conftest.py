"""Pytest fixtures for the Deye Dehumidifier integration."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from libdeye.device_state import DeyeDeviceState
import pytest

from tests.helpers import (
    DEFAULT_STATE_HEX,
    MOCK_DEVICE_INFO,
    FakeDeyeDevice,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Enable loading this repo's custom_components in every test."""
    yield


@pytest.fixture
def mock_deye_cloud_api() -> Generator[MagicMock]:
    """Patch DeyeCloudApi used by config flow so tests never hit Deye Cloud."""
    with patch(
        "custom_components.deye_dehumidifier.config_flow.DeyeCloudApi",
        autospec=True,
    ) as mock_cls:
        api = mock_cls.return_value
        api.auth_token = "mock-auth-token"
        api.user_id = "user-123"
        api.authenticate = AsyncMock()
        yield api


@pytest.fixture
def mock_libdeye() -> Generator[tuple[MagicMock, FakeDeyeDevice]]:
    """Patch cloud API + DeyeClient (and its MQTT pool) used during setup."""
    device = FakeDeyeDevice(MOCK_DEVICE_INFO)
    with (
        patch(
            "custom_components.deye_dehumidifier.DeyeCloudApi",
            autospec=True,
        ) as mock_api_cls,
        patch(
            "custom_components.deye_dehumidifier.DeyeClient",
            autospec=True,
        ) as mock_client_cls,
    ):
        mock_api_cls.return_value.authenticate = AsyncMock()
        client = mock_client_cls.return_value
        client.list_devices = AsyncMock(return_value=[device])
        client.disconnect = MagicMock()
        yield client, device


@pytest.fixture
def fake_device_state() -> DeyeDeviceState:
    """Return a Classic-payload device state (20°C / 60% RH default hex)."""
    return DeyeDeviceState(DEFAULT_STATE_HEX)
