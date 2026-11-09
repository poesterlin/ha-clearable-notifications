"""Config flow: one hub entry, one subentry per notification."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.selector import (
    BooleanSelector,
    DurationSelector,
    DurationSelectorConfig,
    IconSelector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
from homeassistant.helpers.template import Template

from .const import (
    CONF_AUTO_CLEAR_AFTER,
    CONF_ICON,
    CONF_MESSAGE,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_SEVERITY,
    CONF_TITLE,
    DOMAIN,
    SEVERITIES,
    SEVERITY_INFO,
    SUBENTRY_NOTIFICATION,
)

NOTIFICATION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(CONF_SEVERITY, default=SEVERITY_INFO): SelectSelector(
            SelectSelectorConfig(
                options=SEVERITIES,
                mode=SelectSelectorMode.LIST,
                translation_key="severity",
            )
        ),
        vol.Optional(CONF_TITLE): TextSelector(),
        vol.Required(CONF_MESSAGE): TextSelector(TextSelectorConfig(multiline=True)),
        vol.Optional(CONF_ICON): IconSelector(),
        vol.Optional(CONF_AUTO_CLEAR_AFTER): DurationSelector(
            DurationSelectorConfig(enable_day=True)
        ),
        vol.Required(CONF_PERSISTENT_NOTIFICATION, default=False): BooleanSelector(),
    }
)


class ClearableNotificationsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single notifications hub."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm creating the hub; notifications are added afterwards."""
        if user_input is not None:
            return self.async_create_entry(title="Notifications", data={})
        return self.async_show_form(step_id="user")

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Notifications are managed as subentries of the hub."""
        return {SUBENTRY_NOTIFICATION: NotificationSubentryFlow}


class NotificationSubentryFlow(ConfigSubentryFlow):
    """Add or edit a notification."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a new notification."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input)
            if not errors:
                data = dict(user_input)
                return self.async_create_entry(title=data.pop(CONF_NAME), data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                NOTIFICATION_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing notification."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input)
            if not errors:
                data = dict(user_input)
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=data.pop(CONF_NAME), data=data
                )
        suggested = user_input or {CONF_NAME: subentry.title, **subentry.data}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(NOTIFICATION_SCHEMA, suggested),
            errors=errors,
            description_placeholders={"name": subentry.title},
        )

    def _validate(self, user_input: dict[str, Any]) -> dict[str, str]:
        errors: dict[str, str] = {}
        if not user_input.get(CONF_NAME, "").strip():
            errors[CONF_NAME] = "name_required"
        for key in (CONF_TITLE, CONF_MESSAGE):
            if not (value := user_input.get(key)):
                continue
            try:
                Template(value, self.hass).ensure_valid()
            except TemplateError:
                errors[key] = "invalid_template"
        return errors
