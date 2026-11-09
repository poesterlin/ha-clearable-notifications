"""Tests for the notification entity and its actions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
import voluptuous as vol
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    mock_restore_cache,
)

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.clearable_notifications.const import DOMAIN, EVENT_NOTIFICATION

from .conftest import FREEZER, FREEZER_ID, LAUNDRY, LAUNDRY_ID, make_subentry

FREEZER_E = "binary_sensor.freezer_too_warm"
LAUNDRY_E = "binary_sensor.laundry"


async def call(hass: HomeAssistant, service: str, entity_id: str, **data: Any) -> None:
    await hass.services.async_call(
        DOMAIN, service, {"entity_id": entity_id, **data}, blocking=True
    )


def attrs(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    return dict(hass.states.get(entity_id).attributes)


async def test_starts_off(hass: HomeAssistant, hub: MockConfigEntry) -> None:
    state = hass.states.get(FREEZER_E)
    assert state.state == "off"
    assert state.attributes["activation_count"] == 0
    assert state.attributes["acknowledged"] is False
    assert state.attributes["notification_id"] == FREEZER_ID
    assert state.attributes["severity"] == "warning"
    assert state.attributes["severity_rank"] == 2
    assert state.attributes["message"] is None


async def test_activate_renders_templates(hass: HomeAssistant, hub) -> None:
    await call(
        hass, "activate", FREEZER_E, variables={"temp": -9.5, "room": "garage"}
    )
    state = hass.states.get(FREEZER_E)
    assert state.state == "on"
    assert state.attributes["message"] == "Freezer at -9.5 C"
    assert state.attributes["title"] == "Freezer garage"
    assert state.attributes["severity"] == "warning"
    assert state.attributes["activation_count"] == 1
    assert state.attributes["activated_at"] is not None
    assert state.attributes["updated_at"] is not None
    assert state.attributes["icon"] == "mdi:alert"


async def test_activate_without_title_config(hass: HomeAssistant, hub) -> None:
    await call(hass, "activate", LAUNDRY_E)
    state = hass.states.get(LAUNDRY_E)
    assert state.attributes["message"] == "Laundry is done."
    assert state.attributes["title"] is None
    assert state.attributes["icon"] == "mdi:information"


async def test_overrides_used_verbatim(hass: HomeAssistant, hub) -> None:
    await call(
        hass,
        "activate",
        FREEZER_E,
        message="Raw {{ not_rendered }}",
        title="T {{ x }}",
        severity="critical",
    )
    state = hass.states.get(FREEZER_E)
    assert state.attributes["message"] == "Raw {{ not_rendered }}"
    assert state.attributes["title"] == "T {{ x }}"
    assert state.attributes["severity"] == "critical"
    assert state.attributes["severity_rank"] == 3
    assert state.attributes["icon"] == "mdi:alert-octagon"


async def test_activation_count_only_on_off_to_on(hass: HomeAssistant, hub) -> None:
    for _ in range(3):
        await call(hass, "activate", LAUNDRY_E)
    assert attrs(hass, LAUNDRY_E)["activation_count"] == 1
    await call(hass, "clear", LAUNDRY_E)
    await call(hass, "activate", LAUNDRY_E)
    assert attrs(hass, LAUNDRY_E)["activation_count"] == 2


async def test_update_keeps_activated_at(
    hass: HomeAssistant, hub, freezer: FrozenDateTimeFactory
) -> None:
    await call(hass, "activate", LAUNDRY_E)
    first = attrs(hass, LAUNDRY_E)
    freezer.tick(timedelta(minutes=1))
    await call(hass, "activate", LAUNDRY_E, message="Again")
    second = attrs(hass, LAUNDRY_E)
    assert second["activated_at"] == first["activated_at"]
    assert second["updated_at"] != first["updated_at"]
    assert second["message"] == "Again"


async def test_acknowledge(
    hass: HomeAssistant, hub, freezer: FrozenDateTimeFactory
) -> None:
    # No-op while off.
    await call(hass, "acknowledge", LAUNDRY_E)
    state = hass.states.get(LAUNDRY_E)
    assert state.state == "off"
    assert state.attributes["acknowledged"] is False
    assert state.attributes["acknowledged_at"] is None

    await call(hass, "activate", LAUNDRY_E)
    await call(hass, "acknowledge", LAUNDRY_E)
    state = hass.states.get(LAUNDRY_E)
    assert state.state == "on"
    assert state.attributes["acknowledged"] is True
    assert state.attributes["acknowledged_at"] == dt_util.utcnow().isoformat()

    # Acknowledging again keeps the original timestamp.
    stamp = state.attributes["acknowledged_at"]
    freezer.tick(timedelta(minutes=1))
    await call(hass, "acknowledge", LAUNDRY_E)
    assert attrs(hass, LAUNDRY_E)["acknowledged_at"] == stamp


async def test_reactivate_same_or_lower_severity_keeps_ack(
    hass: HomeAssistant, hub
) -> None:
    await call(hass, "activate", FREEZER_E)  # warning
    await call(hass, "acknowledge", FREEZER_E)
    await call(hass, "activate", FREEZER_E)  # same
    assert attrs(hass, FREEZER_E)["acknowledged"] is True
    await call(hass, "activate", FREEZER_E, severity="info")  # lower
    state = hass.states.get(FREEZER_E)
    assert state.attributes["acknowledged"] is True
    assert state.attributes["severity"] == "info"
    assert state.attributes["acknowledged_at"] is not None


async def test_reactivate_higher_severity_resets_ack(hass: HomeAssistant, hub) -> None:
    await call(hass, "activate", FREEZER_E)
    await call(hass, "acknowledge", FREEZER_E)
    await call(hass, "activate", FREEZER_E, severity="critical")
    state = hass.states.get(FREEZER_E)
    assert state.state == "on"
    assert state.attributes["acknowledged"] is False
    assert state.attributes["acknowledged_at"] is None
    assert state.attributes["severity"] == "critical"
    assert state.attributes["activation_count"] == 1


async def test_activate_after_clear_resets_ack(hass: HomeAssistant, hub) -> None:
    await call(hass, "activate", LAUNDRY_E)
    await call(hass, "acknowledge", LAUNDRY_E)
    await call(hass, "clear", LAUNDRY_E)
    await call(hass, "activate", LAUNDRY_E)
    assert attrs(hass, LAUNDRY_E)["acknowledged"] is False


async def test_clear_and_idempotent(hass: HomeAssistant, hub) -> None:
    # Clearing a clear notification changes nothing.
    await call(hass, "clear", LAUNDRY_E)
    assert attrs(hass, LAUNDRY_E)["cleared_at"] is None

    await call(hass, "activate", LAUNDRY_E)
    await call(hass, "clear", LAUNDRY_E)
    state = hass.states.get(LAUNDRY_E)
    assert state.state == "off"
    assert state.attributes["cleared_at"] is not None
    assert state.attributes["auto_clear_at"] is None
    assert state.attributes["icon"] == "mdi:bell-check-outline"

    stamp = state.attributes["cleared_at"]
    await call(hass, "clear", LAUNDRY_E)
    state = hass.states.get(LAUNDRY_E)
    assert state.state == "off"
    assert state.attributes["cleared_at"] == stamp


async def test_set_active(hass: HomeAssistant, hub) -> None:
    await call(hass, "set_active", LAUNDRY_E, active=True, message="Hi")
    state = hass.states.get(LAUNDRY_E)
    assert state.state == "on"
    assert state.attributes["message"] == "Hi"
    await call(hass, "set_active", LAUNDRY_E, active=False)
    assert hass.states.get(LAUNDRY_E).state == "off"
    # cv.boolean accepts strings, e.g. from templates.
    await call(hass, "set_active", LAUNDRY_E, active="true")
    assert hass.states.get(LAUNDRY_E).state == "on"


async def test_entity_id_all(hass: HomeAssistant, hub) -> None:
    await call(hass, "activate", "all")
    assert hass.states.get(FREEZER_E).state == "on"
    assert hass.states.get(LAUNDRY_E).state == "on"
    await call(hass, "acknowledge", "all")
    assert attrs(hass, FREEZER_E)["acknowledged"] is True
    assert attrs(hass, LAUNDRY_E)["acknowledged"] is True
    await call(hass, "clear", "all")
    assert hass.states.get(FREEZER_E).state == "off"
    assert hass.states.get(LAUNDRY_E).state == "off"


async def test_invalid_severity(hass: HomeAssistant, hub) -> None:
    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await call(hass, "activate", LAUNDRY_E, severity="catastrophic")
    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await call(hass, "set_active", LAUNDRY_E, active=True, severity="nope")
    assert hass.states.get(LAUNDRY_E).state == "off"


async def test_template_render_error(hass: HomeAssistant, setup_hub) -> None:
    await setup_hub(
        [make_subentry("sub_bad", "Broken", {"message": "{{ 1 / 0 }}", "severity": "info"})]
    )
    with pytest.raises(HomeAssistantError, match="message template of binary_sensor.broken"):
        await call(hass, "activate", "binary_sensor.broken")
    assert hass.states.get("binary_sensor.broken").state == "off"
    # An explicit message bypasses the broken template.
    await call(hass, "activate", "binary_sensor.broken", message="ok")
    assert hass.states.get("binary_sensor.broken").state == "on"


async def test_title_render_error(hass: HomeAssistant, setup_hub) -> None:
    await setup_hub(
        [make_subentry("sub_bad", "Broken", {"title": "{{ 1 / 0 }}", "message": "m"})]
    )
    with pytest.raises(HomeAssistantError, match="title template"):
        await call(hass, "activate", "binary_sensor.broken")


# ------------------------------------------------------------- auto-clear


async def test_auto_clear(
    hass: HomeAssistant, setup_hub, freezer: FrozenDateTimeFactory
) -> None:
    await setup_hub(
        [make_subentry("sub_hb", "Heartbeat", {"message": "m", "auto_clear_after": {"minutes": 10}})]
    )
    entity = "binary_sensor.heartbeat"
    await call(hass, "activate", entity)
    state = hass.states.get(entity)
    assert state.state == "on"
    assert state.attributes["auto_clear_at"] == (
        dt_util.utcnow() + timedelta(minutes=10)
    ).isoformat()

    freezer.tick(timedelta(minutes=9, seconds=59))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity).state == "on"

    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    state = hass.states.get(entity)
    assert state.state == "off"
    assert state.attributes["cleared_at"] is not None
    assert state.attributes["auto_clear_at"] is None


async def test_reactivation_restarts_auto_clear(
    hass: HomeAssistant, setup_hub, freezer: FrozenDateTimeFactory
) -> None:
    await setup_hub(
        [make_subentry("sub_hb", "Heartbeat", {"message": "m", "auto_clear_after": {"minutes": 10}})]
    )
    entity = "binary_sensor.heartbeat"
    await call(hass, "activate", entity)
    freezer.tick(timedelta(minutes=8))
    async_fire_time_changed(hass)
    await call(hass, "activate", entity)  # restart: now due in 10 minutes

    freezer.tick(timedelta(minutes=5))  # 13 min after the first activation
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity).state == "on"

    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity).state == "off"


async def test_manual_clear_cancels_auto_clear(
    hass: HomeAssistant, setup_hub, freezer: FrozenDateTimeFactory
) -> None:
    await setup_hub(
        [make_subentry("sub_hb", "Heartbeat", {"message": "m", "auto_clear_after": {"minutes": 1}})]
    )
    entity = "binary_sensor.heartbeat"
    events = async_capture_events(hass, EVENT_NOTIFICATION)
    await call(hass, "activate", entity)
    await call(hass, "clear", entity)
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [e.data["type"] for e in events] == ["activated", "cleared"]


# ------------------------------------------------- persistent notification


def _mirror(hass: HomeAssistant, subentry_id: str):
    return persistent_notification._async_get_or_create_notifications(hass).get(
        f"clearable_notifications_{subentry_id}"
    )


@pytest.fixture
async def mirrored(hass: HomeAssistant, setup_hub) -> MockConfigEntry:
    return await setup_hub(
        [
            make_subentry(
                "sub_mirror",
                "Mirror",
                {"title": "Hello", "message": "Body", "persistent_notification": True},
            )
        ]
    )


async def test_mirror_created_and_dismissed_on_clear(hass: HomeAssistant, mirrored) -> None:
    assert _mirror(hass, "sub_mirror") is None
    await call(hass, "activate", "binary_sensor.mirror")
    note = _mirror(hass, "sub_mirror")
    assert note is not None
    assert note["title"] == "Hello"
    assert note["message"] == "Body"

    await call(hass, "clear", "binary_sensor.mirror")
    assert _mirror(hass, "sub_mirror") is None


async def test_mirror_title_falls_back_to_name(hass: HomeAssistant, setup_hub) -> None:
    await setup_hub(
        [make_subentry("sub_m2", "Mirror", {"message": "Body", "persistent_notification": True})]
    )
    await call(hass, "activate", "binary_sensor.mirror")
    assert _mirror(hass, "sub_m2")["title"] == "Mirror"


async def test_dismissing_mirror_acknowledges(hass: HomeAssistant, mirrored) -> None:
    await call(hass, "activate", "binary_sensor.mirror")
    persistent_notification.async_dismiss(hass, "clearable_notifications_sub_mirror")
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.mirror")
    assert state.state == "on"
    assert state.attributes["acknowledged"] is True
    assert state.attributes["acknowledged_at"] is not None

    # Acknowledged notifications are not mirrored again on same-severity updates.
    await call(hass, "activate", "binary_sensor.mirror")
    assert _mirror(hass, "sub_mirror") is None
    # Escalation resets acknowledged and re-creates the mirror.
    await call(hass, "activate", "binary_sensor.mirror", severity="critical")
    assert _mirror(hass, "sub_mirror") is not None


async def test_clear_dismiss_does_not_ack(hass: HomeAssistant, mirrored) -> None:
    await call(hass, "activate", "binary_sensor.mirror")
    await call(hass, "clear", "binary_sensor.mirror")
    await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.mirror")
    assert state.state == "off"
    assert state.attributes["acknowledged"] is False


async def test_acknowledge_action_keeps_mirror(hass: HomeAssistant, mirrored) -> None:
    # Documented behaviour of the code: only dismissing the mirror acknowledges,
    # acknowledging through the action does not touch the sidebar notification.
    await call(hass, "activate", "binary_sensor.mirror")
    await call(hass, "acknowledge", "binary_sensor.mirror")
    assert _mirror(hass, "sub_mirror") is not None


# ----------------------------------------------------------------- restore


async def test_restore_active_acknowledged(hass: HomeAssistant, setup_hub) -> None:
    mock_restore_cache(
        hass,
        [
            State(
                FREEZER_E,
                "on",
                {
                    "severity": "critical",
                    "title": "Old title",
                    "message": "Old message",
                    "acknowledged": True,
                    "activated_at": "2026-11-01T10:00:00+00:00",
                    "updated_at": "2026-11-01T10:05:00+00:00",
                    "acknowledged_at": "2026-11-01T10:06:00+00:00",
                    "auto_clear_at": None,
                    "activation_count": 7,
                },
            )
        ],
    )
    await setup_hub()
    state = hass.states.get(FREEZER_E)
    assert state.state == "on"
    assert state.attributes["acknowledged"] is True
    assert state.attributes["severity"] == "critical"
    assert state.attributes["title"] == "Old title"
    assert state.attributes["message"] == "Old message"
    assert state.attributes["activation_count"] == 7
    assert state.attributes["activated_at"] == "2026-11-01T10:00:00+00:00"
    assert state.attributes["acknowledged_at"] == "2026-11-01T10:06:00+00:00"
    # Restored count continues.
    await call(hass, "clear", FREEZER_E)
    await call(hass, "activate", FREEZER_E, variables={"temp": 1, "room": "x"})
    assert attrs(hass, FREEZER_E)["activation_count"] == 8


async def test_restore_cleared_state(hass: HomeAssistant, setup_hub) -> None:
    mock_restore_cache(
        hass,
        [
            State(
                LAUNDRY_E,
                "off",
                {"cleared_at": "2026-11-01T10:00:00+00:00", "activation_count": 3},
            )
        ],
    )
    await setup_hub()
    state = hass.states.get(LAUNDRY_E)
    assert state.state == "off"
    assert state.attributes["cleared_at"] == "2026-11-01T10:00:00+00:00"
    assert state.attributes["activation_count"] == 3


async def test_restore_expired_auto_clear_is_off(hass: HomeAssistant, setup_hub) -> None:
    past = (dt_util.utcnow() - timedelta(hours=1)).isoformat()
    mock_restore_cache(
        hass,
        [
            State(
                LAUNDRY_E,
                "on",
                {"severity": "info", "message": "m", "auto_clear_at": past, "activation_count": 1},
            )
        ],
    )
    await setup_hub()
    state = hass.states.get(LAUNDRY_E)
    assert state.state == "off"
    assert state.attributes["cleared_at"] == past
    assert state.attributes["auto_clear_at"] is None


async def test_restore_pending_auto_clear_is_rescheduled(
    hass: HomeAssistant, setup_hub, freezer: FrozenDateTimeFactory
) -> None:
    future = (dt_util.utcnow() + timedelta(minutes=5)).isoformat()
    mock_restore_cache(
        hass,
        [State(LAUNDRY_E, "on", {"severity": "info", "message": "m", "auto_clear_at": future})],
    )
    await setup_hub()
    assert hass.states.get(LAUNDRY_E).state == "on"
    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(LAUNDRY_E).state == "off"


async def test_restore_recreates_mirror_unless_acknowledged(
    hass: HomeAssistant, setup_hub
) -> None:
    mock_restore_cache(
        hass,
        [
            State("binary_sensor.a", "on", {"severity": "info", "message": "A", "acknowledged": False}),
            State("binary_sensor.b", "on", {"severity": "info", "message": "B", "acknowledged": True}),
        ],
    )
    cfg = {"message": "m", "persistent_notification": True}
    await setup_hub([make_subentry("sub_a", "A", cfg), make_subentry("sub_b", "B", cfg)])
    assert _mirror(hass, "sub_a") is not None
    assert _mirror(hass, "sub_b") is None


# ------------------------------------------------------------------ events


async def test_events(hass: HomeAssistant, hub) -> None:
    events = async_capture_events(hass, EVENT_NOTIFICATION)
    await call(hass, "activate", LAUNDRY_E)
    await call(hass, "activate", LAUNDRY_E, message="again")
    await call(hass, "acknowledge", LAUNDRY_E)
    await call(hass, "clear", LAUNDRY_E)
    await call(hass, "clear", LAUNDRY_E)  # no event: already clear
    await call(hass, "acknowledge", LAUNDRY_E)  # no event: not active
    await hass.async_block_till_done()

    assert [e.data["type"] for e in events] == [
        "activated",
        "updated",
        "acknowledged",
        "cleared",
    ]
    first = events[0].data
    assert first["entity_id"] == LAUNDRY_E
    assert first["severity"] == "info"
    assert first["message"] == "Laundry is done."
    assert first["title"] is None
    assert events[1].data["message"] == "again"
