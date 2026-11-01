"""Arm when ready: wait for an area's zones to close, then arm it.

Turned on with the area's "Arm when ready" switch (in the mode picked on its
"Arm when ready mode" select) or the protege_wx.arm_when_ready action. While it
waits, every status update checks the zones; as soon as none is open, the area
is armed. It stops when:

* the area arms (by this or anyone else): done;
* the time limit runs out: gives up and says so;
* the switch is turned off, or the area is disarmed after an alarm: cancelled;
* the controller refuses three times in a row: gives up and says why.

Nothing is remembered over a restart, so a restart never arms a house later
than someone expected.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import EVENT_ARM_WHEN_READY, EVENT_LOGBOOK

if TYPE_CHECKING:
    from .alarm_control_panel import ProtegeArea
    from .coordinator import AreaInfo, ProtegeCoordinator

_LOGGER = logging.getLogger(__name__)

# Home Assistant modes this can arm in.
MODES = ("away", "home", "night")


def night_mode_for(area: AreaInfo, configured: str) -> str:
    """What Night arms on the controller for an area: instant, stay or off,
    falling back to off when the area can't arm that way."""
    if configured == "stay" and not area.stay_enabled:
        return "off"
    if configured == "instant" and not area.instant_enabled:
        return "off"
    return configured
_MAX_REFUSALS = 3

RESULT_ARMED = "armed"
RESULT_TIMED_OUT = "timed_out"
RESULT_CANCELLED = "cancelled"
RESULT_FAILED = "failed"

_MESSAGES = {
    RESULT_ARMED: "armed {mode} once every zone was closed",
    RESULT_TIMED_OUT: "gave up arming {mode} after {minutes} min; still open: {zones}",
    RESULT_CANCELLED: "stopped waiting to arm {mode}",
    RESULT_FAILED: "couldn't arm {mode}: {error}",
}


@dataclass
class _Wait:
    mode: str
    minutes: int
    until: datetime
    started_by: str | None
    refusals: int = 0
    busy: bool = False
    cancel_timer: CALLBACK_TYPE | None = None


class ArmWhenReady:
    """The waits running on one controller's areas."""

    def __init__(self, hass: HomeAssistant, coordinator: ProtegeCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._waits: dict[int, _Wait] = {}
        # The mode each area's switch arms in (from its select).
        self.preferred: dict[int, str] = {}
        self._listeners: list[CALLBACK_TYPE] = []
        self._remove: CALLBACK_TYPE | None = None

    # ── state for the entities ─────────────────────────────────────────────

    def waiting(self, area_id: int) -> bool:
        return area_id in self._waits

    def details(self, area_id: int) -> dict[str, Any]:
        wait = self._waits.get(area_id)
        if wait is None:
            return {}
        return {"mode": wait.mode, "until": wait.until.isoformat()}

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # ── lifecycle ──────────────────────────────────────────────────────────

    @callback
    def async_start(self) -> None:
        self._remove = self.coordinator.async_add_listener(self._on_update)

    @callback
    def async_stop(self) -> None:
        if self._remove:
            self._remove()
            self._remove = None
        for wait in self._waits.values():
            if wait.cancel_timer:
                wait.cancel_timer()
        self._waits.clear()

    # ── starting and stopping ──────────────────────────────────────────────

    async def async_begin(
        self, panel: ProtegeArea, mode: str, minutes: int, started_by: str | None = None
    ) -> None:
        """Wait for the area to be ready, then arm it in ``mode``. Arms straight
        away if it's ready now."""
        panel.check_mode_available(mode)
        area_id = panel.rec_id
        status = self.coordinator.data.areas.get(area_id) if self.coordinator.data else None
        if status is not None and status.is_armed_or_arming:
            return  # already armed or arming: nothing to wait for
        self._end(area_id)  # a new request replaces an old one
        until = dt_util.utcnow() + timedelta(minutes=minutes)
        wait = _Wait(mode=mode, minutes=minutes, until=until, started_by=started_by)

        async def _timeout(_now: datetime) -> None:
            wait.cancel_timer = None
            if self._waits.get(area_id) is wait:
                self._finish(panel, RESULT_TIMED_OUT)

        wait.cancel_timer = async_track_point_in_utc_time(self.hass, _timeout, until)
        self._waits[area_id] = wait
        self._notify()
        await self._try(panel, wait)

    @callback
    def async_cancel(self, panel: ProtegeArea) -> None:
        if panel.rec_id in self._waits:
            self._finish(panel, RESULT_CANCELLED)

    # ── checking ───────────────────────────────────────────────────────────

    def _ready(self, area_id: int, mode: str, panel: ProtegeArea) -> bool:
        stay = panel.controller_mode_for(mode) == "stay"
        coordinator = self.coordinator
        return coordinator.zones_known(area_id, stay=stay) and not coordinator.open_zones(
            area_id, stay=stay
        )

    @callback
    def _on_update(self) -> None:
        runtime = getattr(self.coordinator.config_entry, "runtime_data", None)
        if runtime is None:
            return
        for area_id, wait in list(self._waits.items()):
            panel = runtime.areas.get(area_id)
            status = self.coordinator.data.areas.get(area_id)
            if panel is None or status is None or not status.known:
                continue
            if status.is_armed_or_arming and not wait.busy:
                # Armed some other way (keypad, app): nothing left to do.
                self._finish(panel, RESULT_ARMED)
                continue
            if status.in_alarm:
                self._finish(panel, RESULT_CANCELLED)
                continue
            if not wait.busy and self._ready(area_id, wait.mode, panel):
                self.hass.async_create_task(self._try(panel, wait))

    async def _try(self, panel: ProtegeArea, wait: _Wait) -> None:
        area_id = panel.rec_id
        if wait.busy or self._waits.get(area_id) is not wait:
            return
        if not self._ready(area_id, wait.mode, panel):
            return
        wait.busy = True
        # Credit the arm to whoever asked, however long ago that was.
        self.coordinator.ha_actor[area_id] = (wait.started_by or "Arm when ready", time.monotonic())
        try:
            await panel.async_arm_mode(wait.mode)
        except HomeAssistantError as err:
            if self._waits.get(area_id) is not wait:
                return
            if getattr(err, "translation_key", None) == "arm_unconfirmed":
                return  # it may still arm; the next update decides
            wait.refusals += 1
            if wait.refusals >= _MAX_REFUSALS or getattr(err, "translation_key", None) not in (
                "failed_to_arm",
                "failed_to_arm_unknown",
            ):
                self._finish(panel, RESULT_FAILED, error=str(err))
            # Otherwise a zone opened again in between: keep waiting.
            return
        finally:
            wait.busy = False
        if self._waits.get(area_id) is wait:
            self._finish(panel, RESULT_ARMED)

    # ── finishing ──────────────────────────────────────────────────────────

    @callback
    def _end(self, area_id: int) -> _Wait | None:
        wait = self._waits.pop(area_id, None)
        if wait is not None and wait.cancel_timer:
            wait.cancel_timer()
            wait.cancel_timer = None
        return wait

    @callback
    def _finish(self, panel: ProtegeArea, result: str, *, error: str | None = None) -> None:
        wait = self._end(panel.rec_id)
        if wait is None:
            return
        self._notify()
        stay = panel.controller_mode_for(wait.mode) == "stay"
        zones = self.coordinator.open_zones(panel.rec_id, stay=stay) if result == RESULT_TIMED_OUT else []
        message = _MESSAGES[result].format(
            mode=wait.mode,
            minutes=wait.minutes,
            zones=", ".join(zones) or "none",
            error=error or "",
        )
        self.hass.bus.async_fire(
            EVENT_ARM_WHEN_READY,
            {
                "entry_id": self.coordinator.config_entry.entry_id,
                "entity_id": panel.entity_id,
                "area": panel.area.name,
                "mode": wait.mode,
                "result": result,
                "open_zones": zones,
                "error": error,
            },
        )
        self.hass.bus.async_fire(
            EVENT_LOGBOOK,
            {"name": panel.area.name, "message": f"Arm when ready {message}", "entity_id": panel.entity_id},
        )
        if result in (RESULT_TIMED_OUT, RESULT_FAILED):
            _LOGGER.info("%s: arm when ready %s", panel.area.name, message)

