"""Diagnostics for the ICT Protege WX integration.

Diagnostics are meant to be attached to bug reports, so credentials, the
host, serial number, PIN hashes and people's names in event-log lines are
redacted. Nothing extra is requested from the controller.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import ProtegeConfigEntry
from .const import CONF_SERIAL, OPT_PANEL_CODE, OPT_USERS

TO_REDACT = {
    CONF_PASSWORD, CONF_USERNAME, CONF_HOST, CONF_SERIAL, OPT_PANEL_CODE, OPT_USERS,
    "serial", "SerialNumber", "IPAddress",
}

# "... By User Jane Citizen", "User Jane Citizen Entry Granted ...", "... By Jane Citizen"
_USER_PREFIX = re.compile(r"^User .+? (Entry|Exit|Access|Logged|Log|Code|Card|Pin|PIN|Duress|Denied|Granted)\b")
_BY = re.compile(r" By (?!Group |Door |Home Assistant\b|Schedule\b).+$")


def redact_event_text(text: str) -> str:
    text = _USER_PREFIX.sub(lambda m: f"User {REDACTED} {m.group(1)}", text)
    return _BY.sub(f" By {REDACTED}", text)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ProtegeConfigEntry
) -> dict[str, Any]:
    data = entry.runtime_data
    coordinator = data.coordinator
    state = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "protocol": data.client.protocol,
        "events_supported": coordinator.events_supported,
        "site": async_redact_data(asdict(data.site), TO_REDACT),
        "status": {
            "areas": {
                k: {"state": v.state, "flags": sorted(v.flags), "raw": v.raw}
                for k, v in state.areas.items()
            },
            "doors": {k: {"lock": v.lock, "position": v.position} for k, v in state.doors.items()},
            "inputs": {k: {"state": v.state, "bypass": v.bypass} for k, v in state.inputs.items()},
            "trouble_inputs": {k: v.state for k, v in state.trouble_inputs.items()},
            "outputs": {k: v.state for k, v in state.outputs.items()},
            "health": async_redact_data(
                {k: v for k, v in state.health.items() if "mac" not in k.lower()}, TO_REDACT
            ),
            "health_troubles": state.health_troubles,
        },
        "recent_events": [
            {
                "time": parsed.event.time.isoformat() if parsed.event.time else None,
                "kind": parsed.kind,
                "type": parsed.event_type,
                "text": redact_event_text(parsed.event.text),
            }
            for parsed in coordinator.history
        ],
    }
