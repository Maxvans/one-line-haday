"""One Line HaDay integration setup."""
from __future__ import annotations

from pathlib import Path
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN
from .http import async_register_views
from .storage import OneLineHaDayStore

PANEL_JS_FILENAME = "one-line-haday-panel.js"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up One Line HaDay."""
    store = OneLineHaDayStore(hass)
    await store.async_load()
    hass.data.setdefault(DOMAIN, {})["store"] = store
    async_register_views(hass)
    await hass.http.async_register_static_paths([StaticPathConfig(
        f"/{DOMAIN}_static",
        hass.config.path(f"custom_components/{DOMAIN}/www"),
        False,
    )])
    await async_register_panel(
        hass, frontend_url_path="one-line-haday",
        webcomponent_name="one-line-haday-panel", sidebar_title="One Line HaDay",
        sidebar_icon="mdi:book-heart",
        module_url=f"/{DOMAIN}_static/{PANEL_JS_FILENAME}?v=6",
        embed_iframe=False, require_admin=False,
    )
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    return True
