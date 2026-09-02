"""Helpers for dehumidifier config subentries."""

from types import MappingProxyType

from libdeye.cloud_api import (
    DeyeApiResponseDeviceInfo,
    DeyeCloudApi,
    DeyeCloudApiCannotConnectError,
    DeyeCloudApiInvalidAuthError,
)

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_AUTH_TOKEN,
    CONF_DEVICE_ID,
    CONF_MAC,
    CONF_PASSWORD,
    CONF_PRODUCT_ID,
    CONF_USERNAME,
    DOMAIN,
    SUBENTRY_TYPE_DEVICE,
    is_dehumidifier_product_type,
)


def is_supported_dehumidifier(info: DeyeApiResponseDeviceInfo) -> bool:
    """Return True if the cloud device is a dehumidifier we can set up."""
    return is_dehumidifier_product_type(str(info.get("product_type") or ""))


def device_subentry_data(info: DeyeApiResponseDeviceInfo) -> dict[str, str]:
    """Return the unique fields stored on a device subentry."""
    return {
        CONF_DEVICE_ID: info["device_id"],
        CONF_MAC: info["mac"],
        CONF_PRODUCT_ID: info["product_id"],
    }


def create_device_subentry(info: DeyeApiResponseDeviceInfo) -> ConfigSubentry:
    """Build a device subentry from a cloud device-list row."""
    return ConfigSubentry(
        data=MappingProxyType(device_subentry_data(info)),
        subentry_type=SUBENTRY_TYPE_DEVICE,
        title=info["device_name"],
        unique_id=info["device_id"],
    )


def iter_device_subentries(entry: ConfigEntry) -> list[ConfigSubentry]:
    """Return device subentries on a config entry."""
    return [
        subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_DEVICE
    ]


def configured_device_ids(entry: ConfigEntry) -> set[str]:
    """Return device_ids already represented by device subentries."""
    return {
        subentry.unique_id or subentry.data[CONF_DEVICE_ID]
        for subentry in iter_device_subentries(entry)
    }


async def async_list_dehumidifier_infos(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[DeyeApiResponseDeviceInfo]:
    """Fetch dehumidifier device-list rows for a config entry's account."""
    cloud_api = DeyeCloudApi(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_AUTH_TOKEN),
    )
    return [
        info
        for info in await cloud_api.get_device_list()
        if is_supported_dehumidifier(info)
    ]


@callback
def async_link_devices_to_subentries(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Attach existing HA devices and entities to matching device subentries."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)

    for subentry in iter_device_subentries(entry):
        mac = subentry.data[CONF_MAC]
        if device := dev_reg.async_get_device(identifiers={(DOMAIN, mac)}):
            dev_reg.async_update_device(
                device.id,
                add_config_entry_id=entry.entry_id,
                add_config_subentry_id=subentry.subentry_id,
            )
        for entity_entry in entities:
            unique_id = entity_entry.unique_id
            if unique_id != mac and not unique_id.startswith(f"{mac}-"):
                continue
            if entity_entry.config_subentry_id == subentry.subentry_id:
                continue
            ent_reg.async_update_entity(
                entity_entry.entity_id,
                config_entry_id=entry.entry_id,
                config_subentry_id=subentry.subentry_id,
            )


@callback
def async_ensure_device_subentries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    devices: list[DeyeApiResponseDeviceInfo],
) -> list[ConfigSubentry]:
    """Create missing device subentries and link existing HA devices."""
    existing = configured_device_ids(entry)
    created: list[ConfigSubentry] = []
    for info in devices:
        if info["device_id"] in existing:
            continue
        subentry = create_device_subentry(info)
        hass.config_entries.async_add_subentry(entry, subentry)
        created.append(subentry)
        existing.add(info["device_id"])
    async_link_devices_to_subentries(hass, entry)
    return created


@callback
def async_remove_stale_device_subentries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    current_device_ids: set[str],
) -> None:
    """Drop device subentries that are no longer on the Deye account."""
    for subentry in list(iter_device_subentries(entry)):
        device_id = subentry.unique_id or subentry.data[CONF_DEVICE_ID]
        if device_id not in current_device_ids:
            hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)


def subentry_id_map(entry: ConfigEntry) -> dict[str, str]:
    """Map cloud device_id to the matching config subentry id."""
    return {
        (subentry.unique_id or subentry.data[CONF_DEVICE_ID]): subentry.subentry_id
        for subentry in iter_device_subentries(entry)
    }


async def async_migrate_v1_device_subentries(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[ConfigSubentry]:
    """Create device subentries from the current cloud device list.

    Used by VERSION 1 -> 2 migration. A failed cloud fetch leaves the
    entry with no subentries; ``async_setup_entry`` will retry.
    """
    try:
        devices = await async_list_dehumidifier_infos(hass, entry)
    except DeyeCloudApiCannotConnectError, DeyeCloudApiInvalidAuthError:
        return []
    return async_ensure_device_subentries(hass, entry, devices)
