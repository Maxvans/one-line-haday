"""Config flow for One Line HaDay.

Single-instance setup: the integration stores no external credentials
(everything is local), so the flow just confirms installation.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries

from .const import DOMAIN


class OneLineHaDayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for One Line HaDay."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="One Line HaDay", data={})

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
