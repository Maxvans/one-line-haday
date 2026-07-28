"""The One Line HaDay integration.

A shared "one line a day" journal for Home Assistant households. Every
authenticated Home Assistant user can write an entry for today, filter
entries by author, and attach photos, all from a sidebar panel — no
separate add-on, container, or exposed port required.
"""
from __future__ import annotations

import logging

from datetime import timedelta
from pathlib import Path as _Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

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
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/{DOMAIN}_static",
                hass.config.path(f"custom_components/{DOMAIN}/www"),
                False,
            )
        ]
    )

    try:
        await async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name="one-line-haday-panel",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            # ?v=6 busts the browser/HA JS cache after this authentication fix.
            module_url=f"/{DOMAIN}_static/{PANEL_JS_FILENAME}?v=6",
            embed_iframe=False,
            require_admin=False,
        )
    except ValueError:
        # Panel already registered (e.g. reload of the config entry).
        _LOGGER.debug("Panel for %s already registered", DOMAIN)

    async def _async_run_retention_cleanup(now) -> None:
        """Delete entries (and their photos) older than each journal's retention window."""
        today_iso = dt_util.now().date().isoformat()
        for journal in store.list_all_journals():
            expired = store.find_expired_entries(journal["id"], today_iso)
            for entry in expired:
                photos = await store.async_delete_entry(entry["id"])
                for photo in photos:
                    file_path = _Path(hass.config.path("www", photo["relative_path"]))
                    file_path.unlink(missing_ok=True)
            if expired:
                _LOGGER.info(
                    "One Line HaDay: purged %d expired entries from journal %s",
                    len(expired),
                    journal["id"],
                )

    unsub = async_track_time_interval(
        hass, _async_run_retention_cleanup, timedelta(hours=24)
    )
    hass.data[DOMAIN]["unsub_retention"] = unsub

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    domain_data = hass.data.pop(DOMAIN, None)
    if domain_data and domain_data.get("unsub_retention"):
        domain_data["unsub_retention"]()
    frontend = hass.data.get("frontend_panels", {})
    frontend.pop(PANEL_URL, None)
    return True
