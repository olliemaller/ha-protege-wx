"""Voice questions for Assist (English).

* "Is the house armed?" - each area's state.
* "Can I arm?" - whether it's ready, or which zones are open.
* "Who came in last?" - the last person let in at a door.

The sentences are registered once for all controllers, and answered from
every loaded one.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .describe import join_names

_LOGGER = logging.getLogger(__name__)
_KEY = "voice"

SENTENCES: dict[str, list[str]] = {
    "armed": [
        "is the (house|home|alarm) (armed|on|set)",
        "is the alarm armed",
        "(what's|what is) the alarm (doing|status|state)",
        "alarm status",
    ],
    "ready": [
        "can I arm [the (house|home|alarm)]",
        "is the (house|home|alarm) ready [to arm]",
        "is it (safe|ok|okay) to arm [the (house|home|alarm)]",
        "(what's|what is|anything) open",
    ],
    "last_in": [
        "who came (in|home) last",
        "who (arrived|got home) last",
        "who was the last (one|person) (in|home)",
        "who (came|got) in last",
    ],
}

_STATE_WORDS = {
    "armed_away": "armed away",
    "armed_home": "armed home",
    "armed_night": "armed for the night",
    "armed_vacation": "armed for holidays",
    "armed_custom_bypass": "armed",
    "arming": "arming",
    "pending": "in its entry delay",
    "disarming": "disarming",
    "triggered": "in alarm",
    "disarmed": "disarmed",
}


def _entries(hass: HomeAssistant) -> list:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _area_entities(entry) -> list:
    return [
        area for area in entry.runtime_data.areas.values()
        if area.entity_id and area.area.has_inputs is not False
    ]


def answer_armed(hass: HomeAssistant) -> str:
    parts = []
    for entry in _entries(hass):
        for area in _area_entities(entry):
            state = hass.states.get(area.entity_id)
            if state is None or state.state in ("unavailable", "unknown"):
                parts.append(f"I can't reach the {area.area.name} right now")
            else:
                parts.append(f"The {area.area.name} is {_STATE_WORDS.get(state.state, state.state)}")
    return (". ".join(parts) + ".") if parts else "There's no alarm set up."


def answer_ready(hass: HomeAssistant) -> str:
    parts = []
    for entry in _entries(hass):
        coordinator = entry.runtime_data.coordinator
        for area in _area_entities(entry):
            status = coordinator.data.areas.get(area.rec_id)
            name = area.area.name
            if status is not None and status.is_armed_or_arming:
                parts.append(f"The {name} is already armed")
            elif not coordinator.zones_known(area.rec_id, stay=False):
                parts.append(f"I can't tell if the {name} is ready right now")
            elif zones := coordinator.open_zones(area.rec_id, stay=False):
                verb = "is" if len(zones) == 1 else "are"
                home_ok = area.area.stay_enabled and not coordinator.open_zones(area.rec_id, stay=True)
                extra = ", but you can arm it in home mode" if home_ok else ""
                parts.append(f"Not yet: {join_names(zones)} {verb} open{extra}")
            else:
                parts.append(f"Yes, the {name} is ready to arm")
    return (". ".join(parts) + ".") if parts else "There's no alarm set up."


def _when(moment: datetime) -> str:
    local = dt_util.as_local(moment)
    clock = local.strftime("%I:%M %p").lstrip("0").lower()
    today = dt_util.now().date()
    if local.date() == today:
        return f"at {clock}"
    if (today - local.date()).days == 1:
        return f"yesterday at {clock}"
    return f"on {local.strftime('%A %d %B').replace(' 0', ' ')} at {clock}"


def answer_last_in(hass: HomeAssistant) -> str:
    latest: tuple[datetime, str, dict[str, Any]] | None = None
    for entry in _entries(hass):
        cached = hass.data.get(DOMAIN, {}).get(("people", entry.entry_id))
        people = cached[1] if cached else {}
        for name, record in people.items():
            moment = dt_util.parse_datetime(record.get("time") or "")
            if moment and (latest is None or moment > latest[0]):
                latest = (moment, name, record)
    if latest is None:
        return "Nobody has come in with a card or PIN that I know of."
    moment, name, record = latest
    door = f" at the {record['door']}" if record.get("door") else ""
    return f"{name}, {_when(moment)}{door}."


_ANSWERS = {"armed": answer_armed, "ready": answer_ready, "last_in": answer_last_in}


def _register(hass: HomeAssistant, sentences: list[str], handler) -> CALLBACK_TYPE | None:
    """Register sentences with Assist, across Home Assistant versions."""
    try:
        from homeassistant.components.conversation.agent_manager import (
            get_agent_manager,
        )
        from homeassistant.components.conversation.trigger import TriggerDetails
    except ImportError:  # before 2025.7: triggers lived on the default agent
        try:
            from homeassistant.components.conversation.const import DATA_DEFAULT_ENTITY

            agent = hass.data.get(DATA_DEFAULT_ENTITY)
            return agent.register_trigger(sentences, handler) if agent else None
        except ImportError:
            return None
    return get_agent_manager(hass).register_trigger(TriggerDetails(sentences, handler))


@callback
def async_setup_voice(hass: HomeAssistant) -> CALLBACK_TYPE:
    """Register the sentences (once); returns a release for the entry's unload."""
    store: dict = hass.data.setdefault(DOMAIN, {})
    state = store.setdefault(_KEY, {"users": 0, "remove": []})
    state["users"] += 1
    if state["users"] == 1 and "conversation" in hass.config.components:
        for key, sentences in SENTENCES.items():
            answer = _ANSWERS[key]

            async def handler(_user_input, _result, answer=answer) -> str:
                return answer(hass)

            try:
                remove = _register(hass, sentences, handler)
            except Exception:  # noqa: BLE001 - voice is optional
                _LOGGER.debug("Couldn't register Assist sentences", exc_info=True)
                remove = None
            if remove:
                state["remove"].append(remove)

    @callback
    def release() -> None:
        state["users"] -= 1
        if state["users"] <= 0:
            for remove in state["remove"]:
                remove()
            store.pop(_KEY, None)

    return release
