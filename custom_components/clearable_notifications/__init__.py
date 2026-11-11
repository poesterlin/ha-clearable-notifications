"""Clearable Notifications: stateful notifications you raise and clear from automations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .frontend import async_register_card
from .services import async_setup_services

if TYPE_CHECKING:
    from .binary_sensor import ClearableNotificationEntity

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class NotificationsData:
    """Runtime data shared between the platforms of one config entry."""

    notifications: dict[str, ClearableNotificationEntity] = field(default_factory=dict)


type NotificationsConfigEntry = ConfigEntry[NotificationsData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions and the dashboard card once per Home Assistant start."""
    async_setup_services(hass)
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NotificationsConfigEntry) -> bool:
    """Set up the notifications hub and all notification subentries."""
    entry.runtime_data = NotificationsData()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Adding, editing or removing a notification updates the entry: reload so the
    # entity set matches. Entity state survives through RestoreEntity.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NotificationsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: NotificationsConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
