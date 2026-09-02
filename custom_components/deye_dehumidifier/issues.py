"""Issue registry repairs for the Deye Dehumidifier integration."""

from datetime import datetime
import logging

from libdeye.client import DeyeClient
from libdeye.cloud_api import DeyeApiResponseDeviceInfo
from libdeye.const import PRODUCT_FEATURE_CONFIG

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ISSUE_MQTT_DISCONNECTED,
    ISSUE_TRACKER_URL,
    ISSUE_UNKNOWN_PRODUCT,
    MQTT_DISCONNECT_CHECK_INTERVAL,
    MQTT_DISCONNECT_ISSUE_DELAY,
)

_LOGGER = logging.getLogger(__name__)


def uses_default_feature_config(product_id: str) -> bool:
    """Return True if this product_id is not in libdeye's known feature map."""
    return product_id not in PRODUCT_FEATURE_CONFIG


def unknown_product_issue_id(entry_id: str, device_id: str) -> str:
    """Return the issue id for an unmapped product on a config entry."""
    return f"{ISSUE_UNKNOWN_PRODUCT}_{entry_id}_{device_id}"


def mqtt_disconnected_issue_id(entry_id: str) -> str:
    """Return the issue id for a prolonged MQTT disconnect on a config entry."""
    return f"{ISSUE_MQTT_DISCONNECTED}_{entry_id}"


def mqtt_client_is_connected(mqtt_client: object) -> bool | None:
    """Return the paho connected flag when the MQTT wrapper exposes it."""
    paho_client = getattr(mqtt_client, "_mqtt", None)
    is_connected = getattr(paho_client, "is_connected", None)
    if not callable(is_connected):
        return None
    return bool(is_connected())


def pooled_mqtt_clients_connected(client: DeyeClient) -> bool | None:
    """Return True if every pooled MQTT client is connected.

    None means no clients have been started or the connected flag is unavailable.
    """
    mqtt_by_type = getattr(client, "_mqtt_by_type", None)
    if not isinstance(mqtt_by_type, dict) or not mqtt_by_type:
        return None
    results = [
        mqtt_client_is_connected(mqtt_client) for mqtt_client in mqtt_by_type.values()
    ]
    if any(result is None for result in results):
        return None
    return all(result is True for result in results)


def async_sync_unknown_product_issues(
    hass: HomeAssistant,
    entry_id: str,
    devices: list[DeyeApiResponseDeviceInfo],
) -> None:
    """Create or delete unknown-product repairs for the current device list."""
    wanted: set[str] = set()
    for device in devices:
        issue_id = unknown_product_issue_id(entry_id, device["device_id"])
        if not uses_default_feature_config(device["product_id"]):
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            continue
        wanted.add(issue_id)
        _LOGGER.warning(
            "Device %s (%s) uses the default feature config; product_id=%s is unmapped",
            device["device_name"],
            device.get("product_name", ""),
            device["product_id"],
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_UNKNOWN_PRODUCT,
            translation_placeholders={
                "name": device["device_name"],
                "product_id": device["product_id"],
                "product_name": device.get("product_name") or device["product_id"],
            },
            learn_more_url=ISSUE_TRACKER_URL,
        )

    prefix = f"{ISSUE_UNKNOWN_PRODUCT}_{entry_id}_"
    issue_reg = ir.async_get(hass)
    for domain, issue_id in list(issue_reg.issues):
        if domain == DOMAIN and issue_id.startswith(prefix) and issue_id not in wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


def async_delete_entry_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Delete all repairs created for a config entry."""
    ir.async_delete_issue(hass, DOMAIN, mqtt_disconnected_issue_id(entry_id))
    prefix = f"{ISSUE_UNKNOWN_PRODUCT}_{entry_id}_"
    issue_reg = ir.async_get(hass)
    for domain, issue_id in list(issue_reg.issues):
        if domain == DOMAIN and issue_id.startswith(prefix):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


class MqttDisconnectMonitor:
    """Raise a repair if pooled MQTT clients stay disconnected too long."""

    def __init__(self, hass: HomeAssistant, entry_id: str, client: DeyeClient) -> None:
        """Initialize the monitor for one config entry."""
        self.hass = hass
        self.entry_id = entry_id
        self.client = client
        self._disconnected_since: datetime | None = None
        self._unsub: CALLBACK_TYPE | None = None
        self._stopped = False

    def async_start(self) -> None:
        """Start periodic checks and evaluate the current connection."""
        self._stopped = False
        self._unsub = async_track_time_interval(
            self.hass, self.async_check, MQTT_DISCONNECT_CHECK_INTERVAL
        )
        self.async_check()

    @callback
    def async_stop(self) -> None:
        """Stop checks and delete the MQTT repair if it exists."""
        self._stopped = True
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self.async_clear()

    @callback
    def async_clear(self) -> None:
        """Clear disconnect tracking and delete the MQTT repair."""
        self._disconnected_since = None
        ir.async_delete_issue(
            self.hass, DOMAIN, mqtt_disconnected_issue_id(self.entry_id)
        )

    @callback
    def async_check(self, now: datetime | None = None) -> None:
        """Create or delete the MQTT repair based on pooled client state."""
        if self._stopped:
            return
        if now is None:
            now = dt_util.utcnow()

        connected = pooled_mqtt_clients_connected(self.client)
        if connected is not False:
            if connected is True:
                self.async_clear()
            return

        if self._disconnected_since is None:
            self._disconnected_since = now
            return

        if now - self._disconnected_since < MQTT_DISCONNECT_ISSUE_DELAY:
            return

        minutes = str(int(MQTT_DISCONNECT_ISSUE_DELAY.total_seconds() // 60))
        _LOGGER.warning(
            "Deye MQTT has been disconnected for more than %s minutes", minutes
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            mqtt_disconnected_issue_id(self.entry_id),
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_MQTT_DISCONNECTED,
            translation_placeholders={"minutes": minutes},
        )
