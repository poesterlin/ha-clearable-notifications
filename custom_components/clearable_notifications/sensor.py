"""Hub-wide summary and current-notification sensors, plus per-notification text sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_ACKNOWLEDGED,
    ATTR_ACTIVATED_AT,
    ATTR_MESSAGE,
    ATTR_SEVERITY,
    ATTR_TITLE,
    DOMAIN,
    SEVERITIES,
    SEVERITY_NONE,
    SEVERITY_RANK,
    SUBENTRY_NOTIFICATION,
    signal_updated,
)

if TYPE_CHECKING:
    from . import NotificationsConfigEntry

PARALLEL_UPDATES = 0

# Home Assistant rejects states longer than 255 characters.
MAX_STATE_LENGTH = 255
ATTR_TEXT = "text"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NotificationsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hub-wide summary sensors and the per-notification text sensors."""
    async_add_entities(
        [
            ActiveNotificationsSensor(entry),
            HighestSeveritySensor(entry),
            CurrentNotificationSensor(entry, ATTR_TITLE),
            CurrentNotificationSensor(entry, ATTR_MESSAGE),
            CurrentNotificationSensor(entry, ATTR_SEVERITY),
        ]
    )
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_NOTIFICATION:
            continue
        async_add_entities(
            [
                NotificationTextSensor(entry, subentry, ATTR_TITLE),
                NotificationTextSensor(entry, subentry, ATTR_MESSAGE),
            ],
            config_subentry_id=subentry.subentry_id,
        )


def hub_device_info(entry: NotificationsConfigEntry) -> DeviceInfo:
    """The "Clearable Notifications" service device that holds hub entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Clearable Notifications",
        entry_type=DeviceEntryType.SERVICE,
    )


def active_notifications(
    hass: HomeAssistant, entry: NotificationsConfigEntry
) -> list[dict[str, Any]]:
    """Active notifications, most severe first, then newest first."""
    items: list[dict[str, Any]] = []
    for entity_id in entry.runtime_data.notifications:
        state = hass.states.get(entity_id)
        if state is None or state.state != STATE_ON:
            continue
        attrs = state.attributes
        items.append(
            {
                "entity_id": entity_id,
                "name": state.name,
                ATTR_TITLE: attrs.get(ATTR_TITLE),
                ATTR_MESSAGE: attrs.get(ATTR_MESSAGE),
                ATTR_SEVERITY: attrs.get(ATTR_SEVERITY),
                ATTR_ACKNOWLEDGED: attrs.get(ATTR_ACKNOWLEDGED, False),
                ATTR_ACTIVATED_AT: attrs.get(ATTR_ACTIVATED_AT),
            }
        )
    items.sort(key=lambda i: i[ATTR_ACTIVATED_AT] or "", reverse=True)
    items.sort(key=lambda i: SEVERITY_RANK.get(i[ATTR_SEVERITY], 0), reverse=True)
    return items


def current_notification(active: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The notification a display should show: most severe, newest unacknowledged."""
    return next((i for i in active if not i[ATTR_ACKNOWLEDGED]), None)


def _state_text(text: str | None) -> str | None:
    """Cut text to the longest state Home Assistant accepts."""
    if text is not None and len(text) > MAX_STATE_LENGTH:
        return text[: MAX_STATE_LENGTH - 1] + "\u2026"
    return text


class _SummarySensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: NotificationsConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"
        self._attr_device_info = hub_device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_updated(self._entry.entry_id), self._async_refresh
            )
        )
        self._async_refresh()

    def _active(self) -> list[dict[str, Any]]:
        return active_notifications(self.hass, self._entry)

    @callback
    def _async_refresh(self) -> None:
        self._update(self._active())
        self.async_write_ha_state()

    def _update(self, active: list[dict[str, Any]]) -> None:
        raise NotImplementedError


class ActiveNotificationsSensor(_SummarySensor):
    """Number of active notifications, with the full list as an attribute."""

    _attr_translation_key = "active"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def _update(self, active: list[dict[str, Any]]) -> None:
        self._attr_native_value = len(active)
        self._attr_icon = "mdi:bell-ring" if active else "mdi:bell-check-outline"
        counts = {
            severity: sum(1 for i in active if i[ATTR_SEVERITY] == severity)
            for severity in SEVERITIES
        }
        self._attr_extra_state_attributes = {
            "unacknowledged": sum(1 for i in active if not i[ATTR_ACKNOWLEDGED]),
            **counts,
            "notifications": active,
        }


class HighestSeveritySensor(_SummarySensor):
    """Highest severity among active notifications (`none` if all clear)."""

    _attr_translation_key = "highest_severity"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [SEVERITY_NONE, *SEVERITIES]

    def _update(self, active: list[dict[str, Any]]) -> None:
        def highest(items: list[dict[str, Any]]) -> str:
            return items[0][ATTR_SEVERITY] if items else SEVERITY_NONE

        self._attr_native_value = highest(active)
        self._attr_extra_state_attributes = {
            "unacknowledged": highest([i for i in active if not i[ATTR_ACKNOWLEDGED]]),
        }


class CurrentNotificationSensor(_SummarySensor):
    """Title, message or severity of the current notification, for displays.

    The current notification is the most severe, newest active one that is not
    acknowledged yet. The state is an empty string when there is none, so a
    display can show an overlay whenever the value is set. Pressing the
    "Dismiss current" button acknowledges it and moves on to the next one.
    """

    def __init__(self, entry: NotificationsConfigEntry, field: str) -> None:
        self._field = field
        self._attr_translation_key = f"current_{field}"
        super().__init__(entry)

    def _update(self, active: list[dict[str, Any]]) -> None:
        current = current_notification(active)
        text: str | None = None
        if current is not None:
            text = current[self._field]
            if self._field == ATTR_TITLE and not text:
                # A display needs a heading; fall back to the notification name.
                text = current["name"]
        self._attr_native_value = _state_text(text) or ""
        self._attr_extra_state_attributes = {
            ATTR_TEXT: text or "",
            "entity_id": current["entity_id"] if current else None,
        }


class NotificationTextSensor(SensorEntity):
    """Read-only title or message of one notification.

    Keeps the last text after the notification is cleared, like the
    attributes of the binary sensor. The state is cut to 255 characters;
    the `text` attribute always holds the full value.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, entry: NotificationsConfigEntry, subentry: ConfigSubentry, field: str
    ) -> None:
        self._entry = entry
        self._notification_id = subentry.subentry_id
        self._field = field
        self._attr_unique_id = f"{subentry.subentry_id}_{field}"
        self._attr_translation_key = f"notification_{field}"
        self._attr_translation_placeholders = {"name": subentry.title}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_updated(self._entry.entry_id), self._async_refresh
            )
        )
        self._async_refresh()

    @callback
    def _async_refresh(self) -> None:
        text: str | None = None
        for notification in self._entry.runtime_data.notifications.values():
            if notification.notification_id == self._notification_id:
                text = getattr(notification, self._field)
                break
        self._attr_native_value = _state_text(text)
        self._attr_extra_state_attributes = {ATTR_TEXT: text}
        self.async_write_ha_state()
