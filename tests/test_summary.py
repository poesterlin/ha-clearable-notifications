"""Tests for the hub-wide summary sensors."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant

from custom_components.clearable_notifications.const import DOMAIN

from .conftest import make_subentry

ACTIVE = "sensor.clearable_notifications_active"
HIGHEST = "sensor.clearable_notifications_highest_severity"


async def call(hass: HomeAssistant, service: str, entity_id: str, **data: Any) -> None:
    await hass.services.async_call(
        DOMAIN, service, {"entity_id": entity_id, **data}, blocking=True
    )


async def test_all_clear(hass: HomeAssistant, hub) -> None:
    state = hass.states.get(ACTIVE)
    assert state.state == "0"
    assert state.attributes["unacknowledged"] == 0
    assert state.attributes["info"] == 0
    assert state.attributes["warning"] == 0
    assert state.attributes["critical"] == 0
    assert state.attributes["notifications"] == []
    assert state.attributes["icon"] == "mdi:bell-check-outline"

    state = hass.states.get(HIGHEST)
    assert state.state == "none"
    assert state.attributes["unacknowledged"] == "none"


async def test_active_sensor(
    hass: HomeAssistant, setup_hub, freezer: FrozenDateTimeFactory
) -> None:
    await setup_hub(
        [
            make_subentry("s1", "Alpha", {"message": "a", "severity": "info"}),
            make_subentry("s2", "Beta", {"message": "b", "severity": "warning"}),
            make_subentry("s3", "Gamma", {"message": "c", "severity": "critical"}),
        ]
    )
    # Activate oldest to newest: alpha (info), beta (warning), gamma (critical).
    for name in ("alpha", "beta", "gamma"):
        await call(hass, "activate", f"binary_sensor.{name}")
        freezer.tick(timedelta(seconds=10))
    await call(hass, "acknowledge", "binary_sensor.gamma")

    state = hass.states.get(ACTIVE)
    assert state.state == "3"
    assert state.attributes["icon"] == "mdi:bell-ring"
    assert state.attributes["unacknowledged"] == 2
    assert state.attributes["info"] == 1
    assert state.attributes["warning"] == 1
    assert state.attributes["critical"] == 1

    notes = state.attributes["notifications"]
    assert [n["entity_id"] for n in notes] == [
        "binary_sensor.gamma",
        "binary_sensor.beta",
        "binary_sensor.alpha",
    ]
    gamma = notes[0]
    assert gamma["name"] == "Gamma"
    assert gamma["message"] == "c"
    assert gamma["severity"] == "critical"
    assert gamma["acknowledged"] is True
    assert gamma["title"] is None
    assert gamma["activated_at"] is not None
    assert notes[1]["acknowledged"] is False


async def test_sorted_newest_first_within_severity(
    hass: HomeAssistant, setup_hub, freezer: FrozenDateTimeFactory
) -> None:
    await setup_hub(
        [
            make_subentry("s1", "One", {"message": "1", "severity": "warning"}),
            make_subentry("s2", "Two", {"message": "2", "severity": "warning"}),
        ]
    )
    await call(hass, "activate", "binary_sensor.one")
    freezer.tick(timedelta(seconds=30))
    await call(hass, "activate", "binary_sensor.two")
    notes = hass.states.get(ACTIVE).attributes["notifications"]
    assert [n["name"] for n in notes] == ["Two", "One"]


async def test_clearing_updates_sensors(hass: HomeAssistant, hub) -> None:
    await call(hass, "activate", "all")
    assert hass.states.get(ACTIVE).state == "2"
    await call(hass, "clear", "binary_sensor.freezer_too_warm")
    assert hass.states.get(ACTIVE).state == "1"
    await call(hass, "clear", "binary_sensor.laundry")
    assert hass.states.get(ACTIVE).state == "0"
    assert hass.states.get(HIGHEST).state == "none"


async def test_highest_severity(hass: HomeAssistant, hub) -> None:
    await call(hass, "activate", "binary_sensor.laundry")  # info
    state = hass.states.get(HIGHEST)
    assert state.state == "info"
    assert state.attributes["unacknowledged"] == "info"

    await call(hass, "activate", "binary_sensor.freezer_too_warm")  # warning
    assert hass.states.get(HIGHEST).state == "warning"

    # Acknowledging the most severe one: highest stays, unacknowledged drops.
    await call(hass, "acknowledge", "binary_sensor.freezer_too_warm")
    state = hass.states.get(HIGHEST)
    assert state.state == "warning"
    assert state.attributes["unacknowledged"] == "info"

    await call(hass, "acknowledge", "binary_sensor.laundry")
    assert hass.states.get(HIGHEST).attributes["unacknowledged"] == "none"

    await call(hass, "activate", "binary_sensor.laundry", severity="critical")
    state = hass.states.get(HIGHEST)
    assert state.state == "critical"
    assert state.attributes["unacknowledged"] == "critical"


FREEZER_TITLE = "sensor.freezer_too_warm_title"
FREEZER_MESSAGE = "sensor.freezer_too_warm_message"
LAUNDRY_TITLE = "sensor.laundry_title"


async def test_text_sensors(hass: HomeAssistant, hub) -> None:
    assert hass.states.get(FREEZER_TITLE).state == "unknown"
    assert hass.states.get(FREEZER_MESSAGE).state == "unknown"

    await call(
        hass,
        "activate",
        "binary_sensor.freezer_too_warm",
        variables={"temp": -9.5, "room": "garage"},
    )
    title = hass.states.get(FREEZER_TITLE)
    assert title.state == "Freezer garage"
    assert title.attributes["text"] == "Freezer garage"
    assert title.attributes["friendly_name"] == "Freezer too warm title"
    message = hass.states.get(FREEZER_MESSAGE)
    assert message.state == "Freezer at -9.5 C"
    assert message.attributes["friendly_name"] == "Freezer too warm message"

    # No configured title: stays unknown.
    await call(hass, "activate", "binary_sensor.laundry")
    assert hass.states.get(LAUNDRY_TITLE).state == "unknown"

    # The last text is kept after clearing.
    await call(hass, "clear", "binary_sensor.freezer_too_warm")
    assert hass.states.get(FREEZER_MESSAGE).state == "Freezer at -9.5 C"


async def test_text_sensor_long_message(hass: HomeAssistant, hub) -> None:
    long = "x" * 400
    await call(hass, "activate", "binary_sensor.freezer_too_warm", message=long)
    state = hass.states.get(FREEZER_MESSAGE)
    assert len(state.state) == 255
    assert state.state.endswith("…")
    assert state.attributes["text"] == long


CUR_TITLE = "sensor.clearable_notifications_current_title"
CUR_MESSAGE = "sensor.clearable_notifications_current_message"
CUR_SEVERITY = "sensor.clearable_notifications_current_severity"
DISMISS = "button.clearable_notifications_dismiss_current"


def current(hass: HomeAssistant) -> tuple[str, str, str]:
    return (
        hass.states.get(CUR_TITLE).state,
        hass.states.get(CUR_MESSAGE).state,
        hass.states.get(CUR_SEVERITY).state,
    )


async def press_dismiss(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": DISMISS}, blocking=True
    )


async def test_current_notification_and_dismiss(
    hass: HomeAssistant, hub, freezer: FrozenDateTimeFactory
) -> None:
    assert current(hass) == ("", "", "")

    await call(hass, "activate", "binary_sensor.laundry")  # info, no title
    assert current(hass) == ("Laundry", "Laundry is done.", "info")
    assert (
        hass.states.get(CUR_MESSAGE).attributes["entity_id"] == "binary_sensor.laundry"
    )

    freezer.tick(timedelta(seconds=5))
    await call(
        hass,
        "activate",
        "binary_sensor.freezer_too_warm",
        variables={"temp": 1, "room": "garage"},
    )  # warning wins
    assert current(hass) == ("Freezer garage", "Freezer at 1 C", "warning")

    # Dismissing acknowledges the shown one; the next one moves up.
    await press_dismiss(hass)
    assert hass.states.get("binary_sensor.freezer_too_warm").attributes["acknowledged"]
    assert hass.states.get("binary_sensor.freezer_too_warm").state == "on"
    assert current(hass) == ("Laundry", "Laundry is done.", "info")

    await press_dismiss(hass)
    assert current(hass) == ("", "", "")
    assert hass.states.get(CUR_MESSAGE).attributes["entity_id"] is None

    # Nothing to dismiss: no error.
    await press_dismiss(hass)

    # Escalating an acknowledged notification shows it again.
    await call(hass, "activate", "binary_sensor.laundry", severity="critical")
    assert current(hass)[2] == "critical"


async def test_current_cleared_by_clear(hass: HomeAssistant, hub) -> None:
    await call(hass, "activate", "binary_sensor.laundry")
    await call(hass, "clear", "binary_sensor.laundry")
    assert current(hass) == ("", "", "")
