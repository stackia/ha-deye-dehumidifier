"""Tests for the Deye Dehumidifier config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

from libdeye.cloud_api import (
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.deye_dehumidifier.const import (
    CONF_AUTH_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.helpers import (
    MOCK_AUTH_TOKEN,
    MOCK_CONFIG,
    MOCK_PASSWORD,
    MOCK_USER_ID,
    MOCK_USERNAME,
)


async def test_user_success(
    hass: HomeAssistant, mock_deye_cloud_api: MagicMock
) -> None:
    """A valid login creates a config entry titled with the username."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.deye_dehumidifier.async_setup_entry",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: MOCK_USERNAME, CONF_PASSWORD: MOCK_PASSWORD},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_USERNAME
    assert result["data"] == {
        CONF_USERNAME: MOCK_USERNAME,
        CONF_PASSWORD: MOCK_PASSWORD,
        CONF_AUTH_TOKEN: MOCK_AUTH_TOKEN,
    }
    mock_deye_cloud_api.authenticate.assert_awaited_once()


async def test_user_invalid_auth(
    hass: HomeAssistant, mock_deye_cloud_api: MagicMock
) -> None:
    """Bad credentials re-show the form with invalid_auth."""
    mock_deye_cloud_api.authenticate = AsyncMock(
        side_effect=DeyeCloudApiInvalidAuthError
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: MOCK_USERNAME, CONF_PASSWORD: MOCK_PASSWORD},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_cannot_connect(
    hass: HomeAssistant, mock_deye_cloud_api: MagicMock
) -> None:
    """A network failure re-shows the form with cannot_connect."""
    mock_deye_cloud_api.authenticate = AsyncMock(
        side_effect=DeyeCloudApiCannotConnectError
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: MOCK_USERNAME, CONF_PASSWORD: MOCK_PASSWORD},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_already_configured(
    hass: HomeAssistant, mock_deye_cloud_api: MagicMock
) -> None:
    """A second entry for the same Deye user_id is aborted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_USER_ID,
        data=MOCK_CONFIG,
        title=MOCK_USERNAME,
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: MOCK_USERNAME, CONF_PASSWORD: MOCK_PASSWORD},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_success(
    hass: HomeAssistant, mock_deye_cloud_api: MagicMock
) -> None:
    """Reauth with a valid password updates the entry and aborts successfully."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_USER_ID,
        data={
            CONF_USERNAME: MOCK_USERNAME,
            CONF_PASSWORD: "old-password",
            CONF_AUTH_TOKEN: "old-token",
        },
        title=MOCK_USERNAME,
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.deye_dehumidifier.async_setup_entry",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: MOCK_PASSWORD},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == MOCK_PASSWORD
    assert entry.data[CONF_AUTH_TOKEN] == MOCK_AUTH_TOKEN
    mock_deye_cloud_api.authenticate.assert_awaited_once()


async def test_reconfigure_success(
    hass: HomeAssistant, mock_deye_cloud_api: MagicMock
) -> None:
    """Reconfigure with a valid password updates the entry and aborts."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_USER_ID,
        data={
            CONF_USERNAME: MOCK_USERNAME,
            CONF_PASSWORD: "old-password",
            CONF_AUTH_TOKEN: "old-token",
        },
        title=MOCK_USERNAME,
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    with patch(
        "custom_components.deye_dehumidifier.async_setup_entry",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: MOCK_PASSWORD},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PASSWORD] == MOCK_PASSWORD
    assert entry.data[CONF_AUTH_TOKEN] == MOCK_AUTH_TOKEN
    mock_deye_cloud_api.authenticate.assert_awaited_once()
