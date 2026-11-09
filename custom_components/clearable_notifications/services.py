"""Actions (services) for Clearable Notifications."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, service

from .const import (
    ATTR_ACTIVE,
    ATTR_MESSAGE,
    ATTR_SEVERITY,
    ATTR_TITLE,
    ATTR_VARIABLES,
    DOMAIN,
    SERVICE_ACKNOWLEDGE,
    SERVICE_ACTIVATE,
    SERVICE_CLEAR,
    SERVICE_SET_ACTIVE,
    SEVERITIES,
)

ACTIVATE_FIELDS = {
    vol.Optional(ATTR_MESSAGE): cv.string,
    vol.Optional(ATTR_TITLE): cv.string,
    vol.Optional(ATTR_SEVERITY): vol.In(SEVERITIES),
    vol.Optional(ATTR_VARIABLES): dict,
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the entity actions of this integration."""
    for name, schema, method in (
        (SERVICE_ACTIVATE, ACTIVATE_FIELDS, "async_activate"),
        (SERVICE_CLEAR, None, "async_clear"),
        (SERVICE_ACKNOWLEDGE, None, "async_acknowledge"),
        (
            SERVICE_SET_ACTIVE,
            {vol.Required(ATTR_ACTIVE): cv.boolean, **ACTIVATE_FIELDS},
            "async_set_active",
        ),
    ):
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=BINARY_SENSOR_DOMAIN,
            schema=schema,
            func=method,
        )
