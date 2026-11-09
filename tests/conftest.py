"""Shared fixtures for the Clearable Notifications tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant

from custom_components.clearable_notifications.const import DOMAIN

FREEZER_ID = "sub_freezer"
LAUNDRY_ID = "sub_laundry"

FREEZER = {
    "severity": "warning",
    "title": "Freezer {{ room }}",
    "message": "Freezer at {{ temp }} C",
    "persistent_notification": False,
}
LAUNDRY = {
    "severity": "info",
    "message": "Laundry is done.",
    "persistent_notification": False,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow Home Assistant to load the integration from custom_components."""


def make_subentry(
    subentry_id: str, title: str, data: dict[str, Any]
) -> ConfigSubentryData:
    """Build subentry data for a notification."""
    return ConfigSubentryData(
        data=data,
        subentry_type="notification",
        title=title,
        unique_id=None,
        subentry_id=subentry_id,
    )


@pytest.fixture
def setup_hub(hass: HomeAssistant) -> Callable[..., Any]:
    """Return a coroutine function that sets up a hub with given subentries."""

    async def _setup(
        subentries: list[ConfigSubentryData] | None = None,
        options: dict[str, Any] | None = None,
    ) -> MockConfigEntry:
        if subentries is None:
            subentries = [
                make_subentry(FREEZER_ID, "Freezer too warm", FREEZER),
                make_subentry(LAUNDRY_ID, "Laundry", LAUNDRY),
            ]
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Notifications",
            data={},
            options=options or {},
            subentries_data=subentries,
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup


@pytest.fixture
async def hub(setup_hub: Callable[..., Any]) -> MockConfigEntry:
    """A loaded hub with a freezer and a laundry notification."""
    return await setup_hub()
