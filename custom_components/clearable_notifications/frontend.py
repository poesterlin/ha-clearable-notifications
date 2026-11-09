"""Serve the bundled Lovelace card so no separate frontend install is needed."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import CARD_FILENAME, CARD_URL_BASE, DOMAIN

WWW_DIR = Path(__file__).parent / "www"


async def async_register_card(hass: HomeAssistant) -> None:
    """Expose the card JS and load it on every frontend page."""
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_BASE, str(WWW_DIR), cache_headers=True)]
    )
    # The version query busts browser caches after an update.
    add_extra_js_url(hass, f"{CARD_URL_BASE}/{CARD_FILENAME}?v={integration.version}")
