"""Diagnostics support for the Deye Dehumidifier integration."""

from collections.abc import Mapping
from enum import Enum
from typing import Any

from libdeye.cloud_api import (
    DeyeApiResponseDeviceInfo,
    DeyeIotPlatform,
    transport_for_device,
)
from libdeye.device_state import DeyeDeviceState

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import ConfigEntryData, DeyeConfigEntry
from .const import CONF_AUTH_TOKEN, CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .data_coordinator import DeyeDataUpdateCoordinator

# Redact credentials from config entry data and any nested MQTT payloads.
TO_REDACT = {
    CONF_PASSWORD,
    CONF_AUTH_TOKEN,
    CONF_USERNAME,
    "password",
    "token",
    "loginname",
    "auth_token",
}

# Device-list fields that are useful for support and do not include secrets.
_DEVICE_METADATA_KEYS = (
    "device_id",
    "deviceid",
    "device_name",
    "alias",
    "product_id",
    "product_name",
    "product_type",
    "producttype_id",
    "platform",
    "mac",
    "protocol_version",
    "online",
    "role",
    "is_combo",
    "gatewaytype",
    "work_time",
    "user_count",
)

_STATE_FIELDS = (
    "anion_switch",
    "water_pump_switch",
    "power_switch",
    "oscillating_switch",
    "child_lock_switch",
    "defrosting",
    "water_tank_full",
    "fan_running",
    "fan_speed",
    "mode",
    "target_humidity",
    "environment_temperature",
    "environment_humidity",
    "uv_switch",
    "prompt_sound",
    "screen_display",
    "timed_off_hour",
)


def _enum_name(value: object) -> str:
    """Return a stable label for an enum or raw platform id."""
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


def _serialize_value(value: object) -> object:
    """Convert enums to names so diagnostics stay JSON-friendly."""
    if isinstance(value, Enum):
        return value.name
    return value


def _platform_label(device: DeyeApiResponseDeviceInfo) -> str:
    """Return Classic / Fog / FogCombo from the device-list platform id."""
    platform = device.get("platform")
    try:
        return DeyeIotPlatform(int(platform)).name
    except TypeError, ValueError:
        return _enum_name(platform)


def _device_metadata(device: DeyeApiResponseDeviceInfo) -> dict[str, Any]:
    """Return non-secret device-list fields plus Classic/Fog labels."""
    raw: Mapping[str, Any] = device
    metadata = {
        key: _serialize_value(raw[key]) for key in _DEVICE_METADATA_KEYS if key in raw
    }
    metadata["platform"] = _platform_label(device)
    metadata["transport"] = _enum_name(transport_for_device(device))
    return metadata


def _state_snapshot(state: DeyeDeviceState) -> dict[str, Any]:
    """Return the current public device state without unused internals."""
    return {
        field: _serialize_value(getattr(state, field))
        for field in _STATE_FIELDS
        if hasattr(state, field)
    }


def _mqtt_connected(mqtt_client: object) -> bool | None:
    """Return paho connected-ish flag when the MQTT wrapper exposes it."""
    paho_client = getattr(mqtt_client, "_mqtt", None)
    is_connected = getattr(paho_client, "is_connected", None)
    if not callable(is_connected):
        return None
    return bool(is_connected())


def _mqtt_clients_snapshot(client: object) -> list[dict[str, Any]]:
    """Return connected-ish flags for pooled Classic/Fog MQTT clients."""
    mqtt_by_type = getattr(client, "_mqtt_by_type", None)
    if not isinstance(mqtt_by_type, dict):
        return []
    snapshots: list[dict[str, Any]] = []
    for client_cls, mqtt_client in sorted(
        mqtt_by_type.items(),
        key=lambda item: getattr(item[0], "__name__", ""),
    ):
        snapshots.append(
            {
                "type": getattr(client_cls, "__name__", type(mqtt_client).__name__),
                "connected": _mqtt_connected(mqtt_client),
                "host": getattr(mqtt_client, "_mqtt_host", None),
                "port": getattr(mqtt_client, "_mqtt_ssl_port", None),
            }
        )
    return snapshots


def _coordinator_snapshot(
    coordinator: DeyeDataUpdateCoordinator | None,
) -> dict[str, Any]:
    """Return availability and a non-secret state snapshot."""
    if coordinator is None or coordinator.data is None:
        return {
            "available": None,
            "last_update_success": None,
            "mqtt_connected": None,
            "state": None,
        }
    device_mqtt = getattr(coordinator, "device", None)
    mqtt_client = getattr(device_mqtt, "_mqtt", None)
    return {
        "available": coordinator.data.available,
        "last_update_success": coordinator.last_update_success,
        "mqtt_connected": _mqtt_connected(mqtt_client) if mqtt_client else None,
        "state": _state_snapshot(coordinator.data.state),
    }


def _device_diagnostics(
    device: DeyeApiResponseDeviceInfo,
    coordinator: DeyeDataUpdateCoordinator | None,
) -> dict[str, Any]:
    """Build diagnostics for one dehumidifier."""
    coordinator_data = _coordinator_snapshot(coordinator)
    metadata = _device_metadata(device)
    return {
        "product_id": metadata.get("product_id"),
        "product_name": metadata.get("product_name"),
        "platform": metadata.get("platform"),
        "transport": metadata.get("transport"),
        "online": metadata.get("online"),
        "available": coordinator_data["available"],
        "device": metadata,
        "state": coordinator_data["state"],
        "last_update_success": coordinator_data["last_update_success"],
        "mqtt_connected": coordinator_data["mqtt_connected"],
    }


def _entry_runtime_data(entry: DeyeConfigEntry) -> ConfigEntryData:
    """Read config-entry runtime data from the typed entry."""
    return entry.runtime_data


def _match_device(
    devices: list[DeyeApiResponseDeviceInfo], device_entry: DeviceEntry
) -> DeyeApiResponseDeviceInfo | None:
    """Find the device-list row for a Home Assistant device registry entry."""
    macs = {
        identifier[1]
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    }
    if device_entry.serial_number:
        macs.add(device_entry.serial_number)
    for device in devices:
        mac = device.get("mac")
        if mac is not None and mac in macs:
            return device
    return None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeyeConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = _entry_runtime_data(entry)
    return async_redact_data(
        {
            "entry": {
                "title": entry.title,
                "domain": entry.domain,
                "entry_id": entry.entry_id,
                "version": entry.version,
                "data": dict(entry.data),
                "options": dict(entry.options),
                "subentries": [
                    {
                        "subentry_id": subentry.subentry_id,
                        "subentry_type": subentry.subentry_type,
                        "title": subentry.title,
                        "unique_id": subentry.unique_id,
                        "data": dict(subentry.data),
                    }
                    for subentry in entry.subentries.values()
                ],
            },
            "mqtt_clients": _mqtt_clients_snapshot(data.client),
            "devices": [
                _device_diagnostics(
                    device, data.coordinator_map.get(device["device_id"])
                )
                for device in data.device_list
            ],
        },
        TO_REDACT,
    )


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: DeyeConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a single device."""
    data = _entry_runtime_data(entry)
    matched = _match_device(data.device_list, device)
    if matched is None:
        return {"error": "Device is not part of this config entry"}
    return async_redact_data(
        _device_diagnostics(matched, data.coordinator_map.get(matched["device_id"])),
        TO_REDACT,
    )
