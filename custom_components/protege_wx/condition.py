"""Automation conditions: "And if ..." building blocks for the automation editor.

* ready_to_arm: every targeted area could be armed now (away, or home, which
  ignores the zones that stay armed only for away). Unknown zones are not
  ready. Also usable in dashboard card visibility from Home Assistant 2026.10.

Needs Home Assistant 2026.10 or later; on older versions this platform offers
nothing and the area's "Ready to arm" binary sensors do the same job.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

# Not in homeassistant.const on every version this supports.
CONF_OPTIONS = "options"
CONF_TARGET = "target"

try:  # Home Assistant 2026.10+
    from homeassistant.helpers.condition import (
        Condition,
        ConditionChecker,
        ConditionConfig,
    )
    from homeassistant.helpers.target import (
        TargetSelection,
        async_extract_referenced_entity_ids,
    )

    SUPPORTED = hasattr(ConditionChecker, "_async_check") and hasattr(
        ConditionChecker, "async_track_changes"
    )
except ImportError:  # pragma: no cover - older Home Assistant
    SUPPORTED = False

CONF_MODE = "mode"
READY_MODES = ("away", "home")

def ready_sensor_for(hass: HomeAssistant, panel_entity_id: str, mode: str) -> str | None:
    """The area's "Ready to arm" binary sensor for a Protege alarm panel."""
    registry = er.async_get(hass)
    panel = registry.async_get(panel_entity_id)
    if panel is None or panel.platform != DOMAIN or panel.domain != "alarm_control_panel":
        return None
    suffix = "_ready_stay" if mode == "home" else "_ready"
    return registry.async_get_entity_id("binary_sensor", DOMAIN, panel.unique_id + suffix)


if SUPPORTED:
    _SCHEMA = vol.Schema(
        {
            vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
            vol.Optional(CONF_OPTIONS, default={}): {
                vol.Optional(CONF_MODE, default="away"): vol.In(READY_MODES),
            },
        }
    )

    class ReadyToArmCondition(Condition):
        """True when every targeted Protege area could be armed now."""

        @classmethod
        async def async_validate_config(cls, hass: HomeAssistant, config: dict[str, Any]) -> dict[str, Any]:
            return _SCHEMA(config)

        def __init__(self, hass: HomeAssistant, config: ConditionConfig) -> None:
            super().__init__(hass, config)
            self._target = config.target or {}
            self._mode = (config.options or {}).get(CONF_MODE, "away")

        def _sensors(self) -> list[str | None]:
            selected = async_extract_referenced_entity_ids(
                self._hass, TargetSelection(self._target)
            )
            registry = er.async_get(self._hass)
            sensors: list[str | None] = []
            for entity_id in sorted(selected.referenced | selected.indirectly_referenced):
                entry = registry.async_get(entity_id)
                if entry is None or entry.platform != DOMAIN or entry.domain != "alarm_control_panel":
                    continue  # another integration's panel, or not a panel at all
                # None (sensor missing) counts as not ready.
                sensors.append(ready_sensor_for(self._hass, entity_id, self._mode))
            return sensors

        def _async_check(self, **kwargs: Any) -> bool | None:
            sensors = self._sensors()
            if not sensors:
                return False
            for sensor in sensors:
                state = self._hass.states.get(sensor) if sensor else None
                if state is None or state.state != STATE_ON:
                    return False
            return True

    CONDITIONS: dict[str, type[Condition]] = {"ready_to_arm": ReadyToArmCondition}
else:  # pragma: no cover - older Home Assistant
    CONDITIONS = {}


async def async_get_conditions(hass: HomeAssistant) -> dict[str, Any]:
    """Return the conditions this integration provides."""
    return CONDITIONS
