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
