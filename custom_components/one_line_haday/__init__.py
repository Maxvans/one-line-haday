"""The One Line HaDay integration.

A shared "one line a day" journal for Home Assistant households. Every
authenticated Home Assistant user can write an entry for today, filter
entries by author, and attach photos, all from a sidebar panel — no
separate add-on, container, or exposed port required.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.panel_custom import async_register_panel

from .const import DOMAIN, PANEL_ICON, PANEL_TITLE, PANEL_URL
from .http import async_register_views
from .storage import OneLineHaDayStore

_LOGGER = logging.getLogger(__name__)

PANEL_JS_FILENAME = "one-line-haday-panel.js"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """YAML setup is not supported; config entries only."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up One Line HaDay from a config entry."""
    store = OneLineHaDayStore(hass)
    await store.async_load()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["store"] = store

    async_register_views(hass)

    # Serve the panel's JS bundle from the integration's own www folder,
    # exposed under /one_line_haday_static, so it doesn't collide with the
    # user's own /config/www content.
    hass.http.register_static_path(
        f"/{DOMAIN}_static",
        hass.config.path(f"custom_components/{DOMAIN}/www"),
        cache_headers=False,
    )

    try:
        await async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name="one-line-haday-panel",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            module_url=f"/{DOMAIN}_static/{PANEL_JS_FILENAME}",
            embed_iframe=False,
            require_admin=False,
        )
    except ValueError:
        # Panel already registered (e.g. reload of the config entry).
        _LOGGER.debug("Panel for %s already registered", DOMAIN)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data.pop(DOMAIN, None)
    frontend = hass.data.get("frontend_panels", {})
    frontend.pop(PANEL_URL, None)
    return True
