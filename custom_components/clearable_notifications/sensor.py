"""Summary sensors across all notifications of the hub."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
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
    """Set up the hub-wide summary sensors."""
    async_add_entities(
        [ActiveNotificationsSensor(entry), HighestSeveritySensor(entry)]
    )


class _SummarySensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: NotificationsConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Clearable Notifications",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_updated(self._entry.entry_id), self._async_refresh
            )
        )
        self._async_refresh()

    def _active(self) -> list[dict[str, Any]]:
        """Active notifications, most severe first, then newest first."""
        items: list[dict[str, Any]] = []
        for entity_id in self._entry.runtime_data.notifications:
            state = self.hass.states.get(entity_id)
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
