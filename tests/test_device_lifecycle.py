"""Tests for dynamic device discovery and stale-device cleanup."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from libdeye.cloud_api import DeyeCloudApiCannotConnectError

from custom_components.deye_dehumidifier import (
    ConfigEntryData,
    async_remove_config_entry_device,
    async_setup_dynamic_entities,
)
from custom_components.deye_dehumidifier.const import (
    DOMAIN,
    SUBENTRY_TYPE_DEVICE,
    is_dehumidifier_product_type,
    is_known_dehumidifier_identifier,
)
from custom_components.deye_dehumidifier.data_coordinator import (
    DeyeDeviceListCoordinator,
)
from custom_components.deye_dehumidifier.subentries import (
    async_ensure_device_subentries,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed


def _device_info(
    device_id: str,
    mac: str,
    product_type: str = "dehumidifier",
    name: str = "Basement",
) -> dict[str, str]:
    return {
        "device_id": device_id,
        "mac": mac,
        "product_type": product_type,
        "device_name": name,
    }


def test_accepts_known_dehumidifier_types() -> None:
    """Dehumidifier / 除湿机 / 其他 are all matching dehumidifiers."""
    assert is_dehumidifier_product_type("dehumidifier")
    assert is_dehumidifier_product_type("除湿机")
    assert is_dehumidifier_product_type("其他")


def test_rejects_other_product_types() -> None:
    """Heaters and unknown types are ignored."""
    assert not is_dehumidifier_product_type("heater")
    assert not is_dehumidifier_product_type("")


def test_identifier_present_on_account() -> None:
    """A MAC still in the cloud list cannot be deleted."""
    assert is_known_dehumidifier_identifier(
        {(DOMAIN, "aa:bb"), ("other", "xx")},
        {"aa:bb"},
    )


def test_identifier_gone_from_account() -> None:
    """A MAC missing from the cloud list can be deleted."""
    assert not is_known_dehumidifier_identifier(
        {(DOMAIN, "aa:bb")},
        {"cc:dd"},
    )


def test_async_remove_config_entry_device_when_gone() -> None:
    """Return True when the device is no longer on the account."""
    hass = MagicMock()
    entry = SimpleNamespace(
        entry_id="entry-1",
        runtime_data=SimpleNamespace(device_list=[_device_info("dev-1", "aa:bb")]),
    )
    device_entry = SimpleNamespace(identifiers={(DOMAIN, "missing-mac")})

    assert asyncio.run(async_remove_config_entry_device(hass, entry, device_entry))


def test_async_remove_config_entry_device_when_present() -> None:
    """Return False while the device is still on the account."""
    hass = MagicMock()
    entry = SimpleNamespace(
        entry_id="entry-1",
        runtime_data=SimpleNamespace(device_list=[_device_info("dev-1", "aa:bb")]),
    )
    device_entry = SimpleNamespace(identifiers={(DOMAIN, "aa:bb")})

    assert not asyncio.run(async_remove_config_entry_device(hass, entry, device_entry))


def test_async_remove_config_entry_device_without_runtime_data() -> None:
    """Allow deletion when the integration has already been unloaded."""
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="entry-1")
    device_entry = SimpleNamespace(identifiers={(DOMAIN, "aa:bb")})

    assert asyncio.run(async_remove_config_entry_device(hass, entry, device_entry))


def _make_list_coordinator(*configured_ids: str) -> DeyeDeviceListCoordinator:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.subentries = {
        f"sub-{device_id}": SimpleNamespace(
            subentry_type=SUBENTRY_TYPE_DEVICE,
            unique_id=device_id,
            data={"device_id": device_id},
            title=device_id,
            subentry_id=f"sub-{device_id}",
        )
        for device_id in configured_ids
    }
    with patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__",
        return_value=None,
    ):
        coordinator = DeyeDeviceListCoordinator(hass, entry, MagicMock(), {}, [])
    coordinator.hass = hass
    coordinator.config_entry = entry
    coordinator._initial_sync = False
    return coordinator


def _cloud_device(device_id: str, mac: str) -> MagicMock:
    device = MagicMock()
    device.device_id = device_id
    device.name = f"Device {device_id}"
    device.info = _device_info(device_id, mac)
    return device


def test_adds_coordinator_for_new_device() -> None:
    """A new matching dehumidifier gets a coordinator."""
    coordinator = _make_list_coordinator("dev-new")
    new_device = _cloud_device("dev-new", "mac-new")
    device_coordinator = MagicMock()
    device_coordinator.async_config_entry_first_refresh = AsyncMock()

    with patch(
        "custom_components.deye_dehumidifier.data_coordinator.DeyeDataUpdateCoordinator",
        return_value=device_coordinator,
    ):
        asyncio.run(coordinator._async_sync_devices([new_device]))

    assert "dev-new" in coordinator.coordinator_map
    assert coordinator.device_list[0]["mac"] == "mac-new"


def test_skips_unconfigured_cloud_device() -> None:
    """Cloud devices without a subentry are listed but not polled."""
    coordinator = _make_list_coordinator()
    new_device = _cloud_device("dev-new", "mac-new")
    device_coordinator = MagicMock()
    device_coordinator.async_config_entry_first_refresh = AsyncMock()

    with patch(
        "custom_components.deye_dehumidifier.data_coordinator.DeyeDataUpdateCoordinator",
        return_value=device_coordinator,
    ):
        asyncio.run(coordinator._async_sync_devices([new_device]))

    assert "dev-new" not in coordinator.coordinator_map
    assert coordinator.device_list[0]["mac"] == "mac-new"
    device_coordinator.async_config_entry_first_refresh.assert_not_called()


def test_failed_discovery_does_not_join_coordinator_map() -> None:
    """A failed first refresh must not leave a device without a coordinator."""
    coordinator = _make_list_coordinator("dev-new")
    new_device = _cloud_device("dev-new", "mac-new")
    device_coordinator = MagicMock()
    device_coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=ConfigEntryNotReady
    )
    device_coordinator.async_shutdown = AsyncMock()

    with patch(
        "custom_components.deye_dehumidifier.data_coordinator.DeyeDataUpdateCoordinator",
        return_value=device_coordinator,
    ):
        asyncio.run(coordinator._async_sync_devices([new_device]))

    assert "dev-new" not in coordinator.coordinator_map
    assert coordinator.device_list == [new_device.info]
    device_coordinator.async_shutdown.assert_awaited_once()


def test_removes_stale_device_from_registry() -> None:
    """A device missing from the cloud list is removed via HA 2026.8 APIs."""
    coordinator = _make_list_coordinator("dev-old")
    stale = MagicMock()
    stale.device.info = _device_info("dev-old", "mac-old")
    stale.async_shutdown = AsyncMock()
    coordinator.coordinator_map["dev-old"] = stale
    coordinator.device_list.append(stale.device.info)

    registry = MagicMock()
    device_entry = MagicMock()
    device_entry.id = "registry-id"
    registry.async_get_device_by_identifier.return_value = device_entry

    with patch(
        "custom_components.deye_dehumidifier.data_coordinator.dr.async_get",
        return_value=registry,
    ):
        asyncio.run(coordinator._async_sync_devices([]))

    stale.async_shutdown.assert_awaited_once()
    registry.async_get_device_by_identifier.assert_called_once_with(
        (DOMAIN, "mac-old"), "entry-1"
    )
    registry.async_remove_device.assert_called_once_with("registry-id")
    assert "dev-old" not in coordinator.coordinator_map
    assert coordinator.device_list == []


def test_failed_cloud_fetch_does_not_drop_devices() -> None:
    """A failed list refresh must not treat every device as stale."""
    coordinator = _make_list_coordinator("dev-1")
    existing = MagicMock()
    coordinator.coordinator_map["dev-1"] = existing
    coordinator.device_list.append(_device_info("dev-1", "mac-1"))
    coordinator._client.list_devices = AsyncMock(
        side_effect=DeyeCloudApiCannotConnectError
    )

    try:
        asyncio.run(coordinator._async_update_data())
    except UpdateFailed:
        pass
    else:
        raise AssertionError("expected UpdateFailed")

    assert "dev-1" in coordinator.coordinator_map
    assert coordinator.device_list[0]["device_id"] == "dev-1"


def _runtime_entry(
    device_list: list[dict[str, str]],
    coordinators: dict[str, MagicMock],
    list_coordinator: MagicMock,
) -> SimpleNamespace:
    entry = SimpleNamespace(entry_id="entry-1")
    entry.runtime_data = ConfigEntryData(
        client=MagicMock(),
        device_list=device_list,
        coordinator_map=coordinators,
        device_list_coordinator=list_coordinator,
        subentry_id_map={
            device["device_id"]: f"sub-{device['device_id']}" for device in device_list
        },
        subentry_fingerprint=(),
    )
    entry.async_on_unload = MagicMock()
    return entry


def test_listener_adds_only_new_devices() -> None:
    """The captured async_add_entities callback is used for later devices."""
    hass = MagicMock()
    first = _device_info("dev-1", "mac-1")
    second = _device_info("dev-2", "mac-2")
    coordinators = {"dev-1": MagicMock(), "dev-2": MagicMock()}
    list_coordinator = MagicMock()
    listener_holder: list = []

    def _add_listener(listener):
        listener_holder.append(listener)
        return lambda: None

    list_coordinator.async_add_listener.side_effect = _add_listener
    entry = _runtime_entry([first], coordinators, list_coordinator)
    added: list[list[object]] = []

    def _add(entities, **kwargs):
        added.append(entities)

    async_setup_dynamic_entities(
        hass,
        entry,
        _add,
        lambda coordinator, device: [f"{device['device_id']}:{id(coordinator)}"],
    )

    assert len(added) == 1
    assert added[0][0] == f"dev-1:{id(coordinators['dev-1'])}"

    entry.runtime_data.device_list.extend([second])
    entry.runtime_data.subentry_id_map["dev-2"] = "sub-dev-2"
    listener_holder[0]()

    assert len(added) == 2
    assert added[1][0] == f"dev-2:{id(coordinators['dev-2'])}"


def test_listener_skips_devices_without_coordinator() -> None:
    """A device list row without a coordinator must not abort entity setup."""
    hass = MagicMock()
    first = _device_info("dev-1", "mac-1")
    orphan = _device_info("dev-orphan", "mac-orphan")
    coordinators = {"dev-1": MagicMock()}
    list_coordinator = MagicMock()
    entry = _runtime_entry([first, orphan], coordinators, list_coordinator)
    added: list[list[object]] = []

    def _add(entities, **kwargs):
        added.append(entities)

    async_setup_dynamic_entities(
        hass,
        entry,
        _add,
        lambda coordinator, device: [device["device_id"]],
    )

    assert added == [["dev-1"]]


def test_ensure_creates_subentries_only_when_none_exist() -> None:
    """First setup auto-creates subentries; later devices stay user-managed."""
    hass = MagicMock()
    entry = SimpleNamespace(subentries={}, title="acct", entry_id="entry-1")
    created_ids: list[str] = []

    def _add(_entry, subentry) -> None:
        created_ids.append(subentry.unique_id)
        entry.subentries[subentry.subentry_id] = subentry

    hass.config_entries.async_add_subentry.side_effect = _add
    first = _device_info("dev-1", "mac-1")
    first["product_id"] = "p1"
    second = _device_info("dev-2", "mac-2")
    second["product_id"] = "p2"
    initial: list = [first]
    with_new_device: list = [first, second]

    with patch(
        "custom_components.deye_dehumidifier.subentries.async_link_devices_to_subentries"
    ):
        created = async_ensure_device_subentries(hass, entry, initial)
        skipped = async_ensure_device_subentries(hass, entry, with_new_device)

    assert [subentry.unique_id for subentry in created] == ["dev-1"]
    assert skipped == []
    assert created_ids == ["dev-1"]


def test_unconfigured_coordinator_is_shut_down() -> None:
    """Removing a subentry drops that device's coordinator without registry delete."""
    coordinator = _make_list_coordinator()
    existing = MagicMock()
    existing.async_shutdown = AsyncMock()
    coordinator.coordinator_map["dev-1"] = existing
    still_on_account = _cloud_device("dev-1", "mac-1")

    asyncio.run(coordinator._async_sync_devices([still_on_account]))

    existing.async_shutdown.assert_awaited_once()
    assert "dev-1" not in coordinator.coordinator_map
    assert coordinator.device_list[0]["device_id"] == "dev-1"
