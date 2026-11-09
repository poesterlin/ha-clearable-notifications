"""Tests for the hub config flow and the notification subentry flow."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.clearable_notifications.const import DOMAIN

from .conftest import FREEZER_ID

VALID = {
    "name": "Door open",
    "severity": "critical",
    "title": "Door",
    "message": "The door has been open for {{ minutes }} minutes.",
    "icon": "mdi:door-open",
    "auto_clear_after": {"hours": 0, "minutes": 5, "seconds": 0},
    "persistent_notification": True,
}


async def _start_subentry(hass: HomeAssistant, entry: MockConfigEntry):
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"), context={"source": SOURCE_USER}
    )


async def test_user_step_creates_hub(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Notifications"
    assert result["data"] == {}


async def test_second_hub_aborts(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, title="Notifications", data={}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_subentry_create(hass: HomeAssistant, setup_hub) -> None:
    entry = await setup_hub([])
    result = await _start_subentry(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], VALID
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Door open"
    assert "name" not in result["data"]
    assert result["data"]["severity"] == "critical"
    assert result["data"]["message"] == VALID["message"]
    await hass.async_block_till_done()

    (subentry,) = entry.subentries.values()
    assert subentry.title == "Door open"
    assert "name" not in subentry.data
    # The update listener reloads the entry and creates the entity.
    assert hass.states.get("binary_sensor.door_open").state == "off"


async def test_subentry_invalid_template(hass: HomeAssistant, setup_hub) -> None:
    entry = await setup_hub([])
    result = await _start_subentry(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID, "message": "{{ unclosed"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"message": "invalid_template"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID, "title": "{% if %}"}
    )
    assert result["errors"] == {"title": "invalid_template"}
    assert not entry.subentries


async def test_subentry_blank_name(hass: HomeAssistant, setup_hub) -> None:
    entry = await setup_hub([])
    result = await _start_subentry(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID, "name": "   "}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_required"}
    assert not entry.subentries


async def test_subentry_reconfigure(hass: HomeAssistant, hub: MockConfigEntry) -> None:
    assert hass.states.get("binary_sensor.freezer_too_warm").attributes[
        "severity"
    ] == "warning"

    result = await hub.start_subentry_reconfigure_flow(hass, FREEZER_ID)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # Existing values are prefilled, the name from the subentry title.
    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested["name"] == "Freezer too warm"
    assert suggested["severity"] == "warning"
    assert suggested["message"] == "Freezer at {{ temp }} C"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Freezer alarm",
            "severity": "critical",
            "message": "Too warm!",
            "persistent_notification": False,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    subentry = hub.subentries[FREEZER_ID]
    assert subentry.title == "Freezer alarm"
    assert "name" not in subentry.data
    assert subentry.data["severity"] == "critical"
    assert "title" not in subentry.data

    # After the reload the entity reflects the new configuration.
    # The entity id is kept by the registry, the friendly name follows the title.
    assert hass.states.get("binary_sensor.freezer_alarm") is None
    assert (
        hass.states.get("binary_sensor.freezer_too_warm").attributes["friendly_name"]
        == "Freezer alarm"
    )
    await hass.services.async_call(
        DOMAIN,
        "activate",
        {"entity_id": "binary_sensor.freezer_too_warm"},
        blocking=True,
    )
    state = hass.states.get("binary_sensor.freezer_too_warm")
    assert state.state == "on"
    assert state.attributes["severity"] == "critical"
    assert state.attributes["message"] == "Too warm!"
    assert state.attributes["title"] is None
