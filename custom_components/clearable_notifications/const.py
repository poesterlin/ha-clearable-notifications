"""Constants for the Clearable Notifications integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "clearable_notifications"

SUBENTRY_NOTIFICATION: Final = "notification"

CONF_MESSAGE: Final = "message"
CONF_TITLE: Final = "title"
CONF_SEVERITY: Final = "severity"
CONF_ICON: Final = "icon"
CONF_AUTO_CLEAR_AFTER: Final = "auto_clear_after"
CONF_PERSISTENT_NOTIFICATION: Final = "persistent_notification"

SEVERITY_INFO: Final = "info"
SEVERITY_WARNING: Final = "warning"
SEVERITY_CRITICAL: Final = "critical"
SEVERITIES: Final = [SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL]
SEVERITY_RANK: Final = {severity: rank for rank, severity in enumerate(SEVERITIES, 1)}
SEVERITY_NONE: Final = "none"

SEVERITY_ICONS: Final = {
    SEVERITY_INFO: "mdi:information",
    SEVERITY_WARNING: "mdi:alert",
    SEVERITY_CRITICAL: "mdi:alert-octagon",
}
ICON_CLEARED: Final = "mdi:bell-check-outline"

ATTR_SEVERITY: Final = "severity"
ATTR_SEVERITY_RANK: Final = "severity_rank"
ATTR_TITLE: Final = "title"
ATTR_MESSAGE: Final = "message"
ATTR_ACKNOWLEDGED: Final = "acknowledged"
ATTR_ACTIVATED_AT: Final = "activated_at"
ATTR_UPDATED_AT: Final = "updated_at"
ATTR_CLEARED_AT: Final = "cleared_at"
ATTR_ACKNOWLEDGED_AT: Final = "acknowledged_at"
ATTR_AUTO_CLEAR_AT: Final = "auto_clear_at"
ATTR_ACTIVATION_COUNT: Final = "activation_count"
ATTR_NOTIFICATION_ID: Final = "notification_id"
ATTR_VARIABLES: Final = "variables"
ATTR_ACTIVE: Final = "active"

SERVICE_ACTIVATE: Final = "activate"
SERVICE_CLEAR: Final = "clear"
SERVICE_ACKNOWLEDGE: Final = "acknowledge"
SERVICE_SET_ACTIVE: Final = "set_active"

EVENT_NOTIFICATION: Final = f"{DOMAIN}_event"

CARD_FILENAME: Final = "clearable-notifications-card.js"
CARD_URL_BASE: Final = f"/{DOMAIN}"


def signal_updated(entry_id: str) -> str:
    """Return the dispatcher signal fired when any notification changes."""
    return f"{DOMAIN}_updated_{entry_id}"
