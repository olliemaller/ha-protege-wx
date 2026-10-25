"""Two-way sync between a Protege area and an Alarmo alarm.

Arming or disarming either one does the same to the other, so Alarmo's
automations, sensors and notifications follow the real alarm and the real
alarm follows Alarmo's keypads. The controller stays the authority:

* Protege armed (any way: keypad, card, app, Home Assistant) -> Alarmo is
  armed in the same mode, skipping Alarmo's own exit delay and forcing past
  Alarmo's open sensors, since the controller has already decided.
* Alarmo arming or armed -> the Protege area is armed in that mode. If the
  controller refuses (a zone is open), Alarmo is disarmed again so the two
  never disagree about whether the house is protected.
* Either disarmed -> the other is disarmed.

A change made by the sync itself is recognised and not sent back, so the two
can't bounce off each other.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event

from .const import OPT_ALARMO_AREA, OPT_ALARMO_CODE, OPT_ALARMO_ENTITY

if TYPE_CHECKING:
    from . import ProtegeConfigEntry

_LOGGER = logging.getLogger(__name__)

# A state the sync caused is ignored for this long when it comes back.
_ECHO_WINDOW = 90.0

_ARMED = {
    AlarmControlPanelState.ARMED_AWAY: "away",
    AlarmControlPanelState.ARMED_HOME: "home",
    AlarmControlPanelState.ARMED_NIGHT: "night",
    AlarmControlPanelState.ARMED_VACATION: "vacation",
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS: "away",
}


def _target(state: State | None) -> str | None:
    """What a panel is (or is about to be): away/home/night/vacation/disarmed,
    or None when there's nothing to mirror (unavailable, triggered...)."""
    if state is None:
        return None
    value = state.state
    if value in _ARMED:
        return _ARMED[value]
    if value == AlarmControlPanelState.DISARMED:
        return "disarmed"
    if value == AlarmControlPanelState.ARMING:
        # Alarmo names the mode it's heading for.
        mode = str(state.attributes.get("arm_mode") or "")
        return _ARMED.get(mode) or (mode.removeprefix("armed_") or None)
    return None


class AlarmoSync:
    """Keeps one Protege area and one Alarmo entity in step."""

    def __init__(self, hass: HomeAssistant, entry: ProtegeConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.alarmo_entity: str = entry.options[OPT_ALARMO_ENTITY]
        self.area_id = int(entry.options[OPT_ALARMO_AREA])
        self.code: str | None = entry.options.get(OPT_ALARMO_CODE) or None
        self._sent: dict[str, tuple[str, float]] = {}  # entity -> (target, when)
        self._remove: CALLBACK_TYPE | None = None

    @property
    def _area(self):
        return self.entry.runtime_data.areas.get(self.area_id)

    @callback
    def async_start(self) -> None:
        area = self._area
        if area is None or area.entity_id is None:
            _LOGGER.warning("Alarmo sync: Protege area %s isn't set up", self.area_id)
            return
        self._remove = async_track_state_change_event(
            self.hass, [area.entity_id, self.alarmo_entity], self._on_change
        )

    @callback
    def async_stop(self) -> None:
        if self._remove:
            self._remove()
            self._remove = None

    def _echo(self, entity_id: str, target: str) -> bool:
        sent = self._sent.get(entity_id)
        return bool(sent and sent[0] == target and time.monotonic() - sent[1] < _ECHO_WINDOW)

    @callback
    def _on_change(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        new = _target(event.data.get("new_state"))
        if new is None or new == _target(event.data.get("old_state")):
            return
        if self._echo(entity_id, new):
            return  # the sync did this
        area = self._area
        if area is None:
            return
        if entity_id == area.entity_id:
            other = self.hass.states.get(self.alarmo_entity)
            if _target(other) != new:
                self.hass.async_create_task(self._to_alarmo(new))
        else:
            if _target(self.hass.states.get(area.entity_id)) != new:
                self.hass.async_create_task(self._to_protege(new))

    async def _to_alarmo(self, target: str) -> None:
        self._sent[self.alarmo_entity] = (target, time.monotonic())
        data: dict[str, Any] = {ATTR_ENTITY_ID: self.alarmo_entity}
        if self.code:
            data["code"] = self.code
        try:
            if target == "disarmed":
                await self.hass.services.async_call(
                    "alarm_control_panel", "alarm_disarm", data, blocking=True
                )
            elif self.hass.services.has_service("alarmo", "arm"):
                await self.hass.services.async_call(
                    "alarmo", "arm",
                    {**data, "mode": target, "skip_delay": True, "force": True},
                    blocking=True,
                )
            else:
                await self.hass.services.async_call(
                    "alarm_control_panel", f"alarm_arm_{target}", data, blocking=True
                )
        except HomeAssistantError as err:
            _LOGGER.warning("Alarmo sync: couldn't set %s to %s: %s", self.alarmo_entity, target, err)

    async def _to_protege(self, target: str) -> None:
        area = self._area
        if area is None:
            return
        self._sent[area.entity_id] = (target, time.monotonic())
        try:
            await area.async_sync_to(target)
        except HomeAssistantError as err:
            _LOGGER.warning("Alarmo sync: the controller refused %s: %s", target, err)
            if target != "disarmed":
                # Don't leave Alarmo saying armed while the house isn't.
                await self._to_alarmo("disarmed")
