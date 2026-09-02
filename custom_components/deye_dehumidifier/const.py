"""Constants for the Deye Dehumidifier integration."""

from datetime import timedelta

DOMAIN = "deye_dehumidifier"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_AUTH_TOKEN = "auth_token"
MANUFACTURER = "Ningbo Deye Technology Co., Ltd"

ISSUE_UNKNOWN_PRODUCT = "unknown_product"
ISSUE_MQTT_DISCONNECTED = "mqtt_disconnected"
ISSUE_TRACKER_URL = "https://github.com/stackia/ha-deye-dehumidifier/issues"

# Ignore brief MQTT reconnects; only raise a repair after this long.
MQTT_DISCONNECT_ISSUE_DELAY = timedelta(minutes=15)
MQTT_DISCONNECT_CHECK_INTERVAL = timedelta(minutes=1)

# The product_type was initially set to "dehumidifier"
# but at some point (around 06/18/2025) it was changed to "除湿机" or "其他"
DEHUMIDIFIER_PRODUCT_TYPES = frozenset({"dehumidifier", "除湿机", "其他"})

DEVICE_LIST_UPDATE_INTERVAL = timedelta(minutes=5)


def is_dehumidifier_product_type(product_type: str) -> bool:
    """Return True if the cloud product_type is a dehumidifier we support."""
    return product_type in DEHUMIDIFIER_PRODUCT_TYPES


def is_known_dehumidifier_identifier(
    identifiers: set[tuple[str, str]], current_macs: set[str]
) -> bool:
    """Return True if a device-registry identifier is still on the account."""
    return any(
        domain == DOMAIN and identifier in current_macs
        for domain, identifier in identifiers
    )
