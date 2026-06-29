"""Config flow for Finance Tracker."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries

from .const import DOMAIN


class FinanceTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create the single local Finance Tracker instance."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Create the integration without requiring external credentials."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Finance Tracker", data={})
        return self.async_show_form(step_id="user")
