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
