"""Serve the Protege alarm card and load it into every dashboard.

The card ships inside the integration, so there's no dashboard resource to
add: once the integration is set up, ``custom:protege-alarm-card`` works.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILE = "protege-alarm-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"
_KEY = "card_registered"


async def async_register_card(hass: HomeAssistant) -> None:
    """Register the card once per Home Assistant run (not per entry)."""
    store: dict = hass.data.setdefault(DOMAIN, {})
    if store.get(_KEY) or getattr(hass, "http", None) is None:
        return
    store[_KEY] = True
    path = Path(__file__).parent / "frontend" / CARD_FILE
    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), True)])
        version = await hass.async_add_executor_job(
            lambda: json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]
        )
        # The version busts the browser cache after an update.
        if "frontend" in hass.config.components:
            add_extra_js_url(hass, f"{CARD_URL}?v={version}")
        else:
            _LOGGER.debug("Frontend not loaded; the alarm card needs adding as a resource")
    except Exception:  # noqa: BLE001 - the card is a nice-to-have
        _LOGGER.warning("Couldn't register the Protege alarm card", exc_info=True)
