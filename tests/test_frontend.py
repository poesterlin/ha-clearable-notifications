"""Tests for the bundled Lovelace card registration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant

from custom_components.clearable_notifications.const import CARD_FILENAME, CARD_URL_BASE

CARD_FILE = (
    Path(__file__).parent.parent
    / "custom_components"
    / "clearable_notifications"
    / "www"
    / CARD_FILENAME
)


async def test_card_url_registered(hass: HomeAssistant, hub) -> None:
    assert f"{CARD_URL_BASE}/{CARD_FILENAME}?v=0.1.0" in hass.data[DATA_EXTRA_MODULE_URL].urls


async def test_card_is_served(hass: HomeAssistant, hub, hass_client) -> None:
    client = await hass_client()
    resp = await client.get(f"{CARD_URL_BASE}/{CARD_FILENAME}")
    assert resp.status == 200
    assert await resp.text() == CARD_FILE.read_text()
