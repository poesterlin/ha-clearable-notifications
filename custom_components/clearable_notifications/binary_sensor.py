"""Notification entities: a binary sensor that is on while the notification is active."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import STATE_ON
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.template import Template, TemplateError
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ACKNOWLEDGED,
    ATTR_ACKNOWLEDGED_AT,
    ATTR_ACTIVATED_AT,
    ATTR_ACTIVATION_COUNT,
    ATTR_AUTO_CLEAR_AT,
    ATTR_CLEARED_AT,
    ATTR_MESSAGE,
    ATTR_NOTIFICATION_ID,
    ATTR_SEVERITY,
    ATTR_SEVERITY_RANK,
    ATTR_TITLE,
    ATTR_UPDATED_AT,
    CONF_AUTO_CLEAR_AFTER,
    CONF_AUTO_CLEAR_DEFAULTS,
    CONF_ICON,
    CONF_MESSAGE,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_SEVERITY,
    CONF_TITLE,
    DOMAIN,
    EVENT_NOTIFICATION,
    ICON_CLEARED,
    SEVERITY_ICONS,
    SEVERITY_INFO,
    SEVERITY_RANK,
    SUBENTRY_NOTIFICATION,
    signal_updated,
)

if TYPE_CHECKING:
    from . import NotificationsConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NotificationsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one notification entity per notification subentry."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_NOTIFICATION:
            continue
        async_add_entities(
            [ClearableNotificationEntity(entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return dt_util.parse_datetime(value)
    return None


class ClearableNotificationEntity(RestoreEntity, BinarySensorEntity):
    """A notification that is raised and cleared by automations."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "notification"

    def __init__(self, entry: NotificationsConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the notification from its subentry configuration."""
        self._entry = entry
        self._config = subentry.data
        self._notification_id = subentry.subentry_id
        self._attr_unique_id = subentry.subentry_id
        self._attr_name = subentry.title
        self._attr_is_on = False

        self._severity: str = self._config.get(CONF_SEVERITY, SEVERITY_INFO)
        self._title: str | None = None
        self._message: str | None = None
        self._acknowledged = False
        self._activated_at: datetime | None = None
        self._updated_at: datetime | None = None
        self._cleared_at: datetime | None = None
        self._acknowledged_at: datetime | None = None
        self._auto_clear_at: datetime | None = None
        self._activation_count = 0
        self._unsub_auto_clear: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------------ state

    @property
    def icon(self) -> str:
        """Configured icon, else one that reflects the current severity."""
        if not self.is_on:
            return self._config.get(CONF_ICON) or ICON_CLEARED
        return self._config.get(CONF_ICON) or SEVERITY_ICONS.get(
            self._severity, SEVERITY_ICONS[SEVERITY_INFO]
        )

    @property
    def severity(self) -> str:
        """Current severity."""
        return self._severity

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose everything a card, template or automation needs."""
        return {
            ATTR_SEVERITY: self._severity,
            ATTR_SEVERITY_RANK: SEVERITY_RANK.get(self._severity, 0),
            ATTR_TITLE: self._title,
            ATTR_MESSAGE: self._message,
            ATTR_ACKNOWLEDGED: self._acknowledged,
            ATTR_ACTIVATED_AT: _iso(self._activated_at),
            ATTR_UPDATED_AT: _iso(self._updated_at),
            ATTR_CLEARED_AT: _iso(self._cleared_at),
            ATTR_ACKNOWLEDGED_AT: _iso(self._acknowledged_at),
            ATTR_AUTO_CLEAR_AT: _iso(self._auto_clear_at),
            ATTR_ACTIVATION_COUNT: self._activation_count,
            ATTR_NOTIFICATION_ID: self._notification_id,
        }

    # -------------------------------------------------------------- lifecycle

    async def async_added_to_hass(self) -> None:
        """Restore the previous state and register with the hub."""
        await super().async_added_to_hass()
        self._entry.runtime_data.notifications[self.entity_id] = self

        if self._config.get(CONF_PERSISTENT_NOTIFICATION):
            self.async_on_remove(
                persistent_notification.async_register_callback(
                    self.hass, self._async_persistent_notification_changed
                )
            )

        if (last := await self.async_get_last_state()) is not None:
            self._restore(last.state == STATE_ON, last.attributes)

        if self.is_on and self._auto_clear_at is not None:
            if self._auto_clear_at <= dt_util.utcnow():
                # Expired while Home Assistant was down.
                self._set_cleared(self._auto_clear_at)
            else:
                self._schedule_auto_clear(self._auto_clear_at)

        # Sidebar notifications don't survive a restart; re-create the mirror
        # unless it was already acknowledged, and drop it if mirroring is off.
        if (
            self.is_on
            and not self._acknowledged
            and self._config.get(CONF_PERSISTENT_NOTIFICATION)
        ):
            self._create_persistent_notification()
        elif not self._config.get(CONF_PERSISTENT_NOTIFICATION):
            persistent_notification.async_dismiss(self.hass, self._persistent_id)

        self._async_publish()

    async def async_will_remove_from_hass(self) -> None:
        """Stop timers and unregister from the hub."""
        self._cancel_auto_clear()
        self._entry.runtime_data.notifications.pop(self.entity_id, None)
        async_dispatcher_send(self.hass, signal_updated(self._entry.entry_id))

    def _restore(self, is_on: bool, attrs: Any) -> None:
        self._attr_is_on = is_on
        if attrs.get(ATTR_SEVERITY) in SEVERITY_RANK:
            self._severity = attrs[ATTR_SEVERITY]
        self._title = attrs.get(ATTR_TITLE)
        self._message = attrs.get(ATTR_MESSAGE)
        self._acknowledged = bool(attrs.get(ATTR_ACKNOWLEDGED, False))
        self._activated_at = _parse(attrs.get(ATTR_ACTIVATED_AT))
        self._updated_at = _parse(attrs.get(ATTR_UPDATED_AT))
        self._cleared_at = _parse(attrs.get(ATTR_CLEARED_AT))
        self._acknowledged_at = _parse(attrs.get(ATTR_ACKNOWLEDGED_AT))
        self._auto_clear_at = _parse(attrs.get(ATTR_AUTO_CLEAR_AT)) if is_on else None
        try:
            self._activation_count = int(attrs.get(ATTR_ACTIVATION_COUNT, 0))
        except (TypeError, ValueError):
            self._activation_count = 0

    # ---------------------------------------------------------------- actions

    async def async_activate(
        self,
        message: str | None = None,
        title: str | None = None,
        severity: str | None = None,
        variables: dict[str, Any] | None = None,
    ) -> None:
        """Raise the notification, or update it if it is already active.

        Configured title/message are templates rendered with `variables`;
        values passed to the action are used as-is (automations already
        render their own templates).
        """
        variables = variables or {}
        if message is None:
            message = self._render(CONF_MESSAGE, self._config[CONF_MESSAGE], variables)
        if title is None and (configured := self._config.get(CONF_TITLE)):
            title = self._render(CONF_TITLE, configured, variables)
        severity = severity or self._config.get(CONF_SEVERITY, SEVERITY_INFO)

        now = dt_util.utcnow()
        was_on = bool(self.is_on)
        if not was_on:
            self._activated_at = now
            self._activation_count += 1
            self._reset_acknowledged()
        elif SEVERITY_RANK[severity] > SEVERITY_RANK.get(self._severity, 0):
            # Escalation needs fresh attention even if it was acknowledged.
            self._reset_acknowledged()

        self._attr_is_on = True
        self._severity = severity
        self._title = title or None
        self._message = message
        self._updated_at = now

        self._cancel_auto_clear()
        self._auto_clear_at = None
        if delay := self._auto_clear_delay():
            self._auto_clear_at = now + delay
            self._schedule_auto_clear(self._auto_clear_at)

        if self._config.get(CONF_PERSISTENT_NOTIFICATION) and not self._acknowledged:
            self._create_persistent_notification()

        self._async_publish("updated" if was_on else "activated")

    async def async_clear(self) -> None:
        """Clear the notification because its condition is no longer met."""
        if not self.is_on:
            return
        self._set_cleared(dt_util.utcnow())
        self._async_publish("cleared")

    async def async_acknowledge(self) -> None:
        """Mark an active notification as seen; it stays active until cleared."""
        if not self.is_on or self._acknowledged:
            return
        self._acknowledged = True
        self._acknowledged_at = dt_util.utcnow()
        self._async_publish("acknowledged")

    async def async_set_active(self, active: bool, **kwargs: Any) -> None:
        """Activate or clear depending on a boolean (handy with templates)."""
        if active:
            await self.async_activate(**kwargs)
        else:
            await self.async_clear()

    # ---------------------------------------------------------------- helpers

    @property
    def _persistent_id(self) -> str:
        return f"{DOMAIN}_{self._notification_id}"

    def _create_persistent_notification(self) -> None:
        persistent_notification.async_create(
            self.hass,
            self._message or "",
            title=self._title or self.name,
            notification_id=self._persistent_id,
        )

    def _reset_acknowledged(self) -> None:
        self._acknowledged = False
        self._acknowledged_at = None

    def _render(self, field: str, value: str, variables: dict[str, Any]) -> str:
        try:
            return Template(value, self.hass).async_render(
                variables, parse_result=False
            )
        except TemplateError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="template_error",
                translation_placeholders={
                    "field": field,
                    "entity_id": self.entity_id,
                    "error": str(err),
                },
            ) from err

    def _auto_clear_delay(self) -> timedelta | None:
        # The notification's own setting wins (an explicit 0 disables
        # auto-clear); otherwise use the hub default for the current severity.
        raw = self._config.get(CONF_AUTO_CLEAR_AFTER) or self._entry.options.get(
            CONF_AUTO_CLEAR_DEFAULTS[self._severity]
        )
        if not raw:
            return None
        delay = cv.time_period(raw)
        return delay if delay.total_seconds() > 0 else None

    def _set_cleared(self, when: datetime) -> None:
        self._cancel_auto_clear()
        self._attr_is_on = False
        self._cleared_at = when
        self._auto_clear_at = None
        if self._config.get(CONF_PERSISTENT_NOTIFICATION):
            persistent_notification.async_dismiss(self.hass, self._persistent_id)

    def _schedule_auto_clear(self, when: datetime) -> None:
        self._cancel_auto_clear()

        @callback
        def _expired(_now: datetime) -> None:
            self._unsub_auto_clear = None
            if self.is_on:
                self._set_cleared(dt_util.utcnow())
                self._async_publish("cleared")

        self._unsub_auto_clear = async_track_point_in_utc_time(self.hass, _expired, when)

    def _cancel_auto_clear(self) -> None:
        if self._unsub_auto_clear is not None:
            self._unsub_auto_clear()
            self._unsub_auto_clear = None

    @callback
    def _async_persistent_notification_changed(
        self,
        update_type: persistent_notification.UpdateType,
        notifications: dict[str, persistent_notification.Notification],
    ) -> None:
        """Dismissing the mirrored notification in the sidebar acknowledges it."""
        if (
            update_type == persistent_notification.UpdateType.REMOVED
            and self._persistent_id in notifications
            and self.is_on
        ):
            self.hass.async_create_task(self.async_acknowledge())

    @callback
    def _async_publish(self, change: str | None = None) -> None:
        """Write state, notify the summary sensors and fire an event."""
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, signal_updated(self._entry.entry_id))
        if change is not None:
            self.hass.bus.async_fire(
                EVENT_NOTIFICATION,
                {
                    "entity_id": self.entity_id,
                    "type": change,
                    ATTR_SEVERITY: self._severity,
                    ATTR_TITLE: self._title,
                    ATTR_MESSAGE: self._message,
                },
            )
