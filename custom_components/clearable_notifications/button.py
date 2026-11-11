"""Button that dismisses (acknowledges) the current notification, e.g. from a display."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .sensor import active_notifications, current_notification, hub_device_info

if TYPE_CHECKING:
    from . import NotificationsConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NotificationsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hub button."""
    async_add_entities([DismissCurrentButton(entry)])


class DismissCurrentButton(ButtonEntity):
    """Acknowledge the notification shown by the current-notification sensors."""

    _attr_has_entity_name = True
    _attr_translation_key = "dismiss_current"

    def __init__(self, entry: NotificationsConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"
        self._attr_device_info = hub_device_info(entry)

    async def async_press(self) -> None:
        """Acknowledge the current notification; the next one (if any) moves up."""
        current = current_notification(active_notifications(self.hass, self._entry))
        if current is None:
            return
        if entity := self._entry.runtime_data.notifications.get(current["entity_id"]):
            await entity.async_acknowledge()
