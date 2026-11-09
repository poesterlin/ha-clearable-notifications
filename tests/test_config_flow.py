"""Tests for the hub config flow and the notification subentry flow."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from custom_components.clearable_notifications.const import DOMAIN

from .conftest import FREEZER_ID, make_subentry

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

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "auto_clear_info": {"hours": 1, "minutes": 0, "seconds": 0},
            "auto_clear_warning": {"hours": 0, "minutes": 30, "seconds": 0},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Notifications"
    assert result["data"] == {}
    assert result["options"] == {
        "auto_clear_info": {"hours": 1, "minutes": 0, "seconds": 0},
        "auto_clear_warning": {"hours": 0, "minutes": 30, "seconds": 0},
    }


def _suggested(result) -> dict:
    return {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }


async def test_user_step_suggests_info_hour(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert _suggested(result) == {
        "auto_clear_info": {"hours": 1, "minutes": 0, "seconds": 0}
    }
    assert set(map(str, result["data_schema"].schema)) == {
        "auto_clear_info",
        "auto_clear_warning",
        "auto_clear_critical",
    }


async def test_user_step_empty_input_creates_no_options(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {}


async def test_user_step_drops_zero_durations(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "auto_clear_info": {"hours": 0, "minutes": 0, "seconds": 0},
            "auto_clear_warning": {"hours": 0, "minutes": 0, "seconds": 0},
            "auto_clear_critical": {"hours": 0, "minutes": 0, "seconds": 20},
        },
    )
    assert result["options"] == {
        "auto_clear_critical": {"hours": 0, "minutes": 0, "seconds": 20}
    }


async def test_options_flow_shows_and_saves(
    hass: HomeAssistant, setup_hub, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup_hub(
        [make_subentry("sub_x", "Thing", {"severity": "warning", "message": "m"})],
        options={"auto_clear_info": {"hours": 2, "minutes": 0, "seconds": 0}},
    )
    entity = "binary_sensor.thing"
    await hass.services.async_call(
        DOMAIN, "activate", {"entity_id": entity}, blocking=True
    )
    assert hass.states.get(entity).attributes["auto_clear_at"] is None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert _suggested(result) == {
        "auto_clear_info": {"hours": 2, "minutes": 0, "seconds": 0}
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "auto_clear_info": {"hours": 0, "minutes": 0, "seconds": 0},
            "auto_clear_warning": {"hours": 0, "minutes": 15, "seconds": 0},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "auto_clear_warning": {"hours": 0, "minutes": 15, "seconds": 0}
    }
    await hass.async_block_till_done()
    assert entry.options == result["data"]

    # The entry was reloaded; the new default applies to the next activation.
    await hass.services.async_call(
        DOMAIN, "activate", {"entity_id": entity}, blocking=True
    )
    assert hass.states.get(entity).attributes["auto_clear_at"] == (
        dt_util.utcnow() + timedelta(minutes=15)
    ).isoformat()


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
