"""Discovery, polling and event handling for the ICT Protege WX integration.

Polling is split so the controller isn't asked for more than it needs:

* every tick (default 1 s): area status, input status and the latest page of
  the event log. These carry arming, motion and "who did what";
* door, trouble-input and output status: when an event says something
  relevant changed, and at least every ``FULL_REFRESH_SECONDS``;
* controller health: every ``HEALTH_REFRESH_SECONDS``.

All of it goes over the client's single session, one request at a time.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_FAILED_TO_ARM,
    EVENT_HISTORY,
    EVENT_LOG,
    FULL_REFRESH_SECONDS,
    HEALTH_REFRESH_SECONDS,
    OPT_NOTIFY_FAILED_ARM,
    OPT_OUTPUTS,
    OPT_SCAN_INTERVAL,
)
from .users import UserCodes
from .wxapi import (
    NO_RECORD,
    TBL_AREAS,
    TBL_DOORS,
    TBL_INPUT_TYPES,
    TBL_INPUTS,
    TBL_OUTPUTS,
    TBL_TROUBLE_INPUTS,
    AreaStatus,
    DoorStatus,
    EventParser,
    InputStatus,
    OutputStatus,
    ParsedEvent,
    ProtegeAuthError,
    ProtegeClient,
    ProtegeError,
    ProtegeEvent,
)
from .wxapi.events import (
    KIND_ACCESS,
    KIND_AREA,
    KIND_DOOR,
    KIND_INPUT,
    KIND_NOISE,
    KIND_TROUBLE,
)

_LOGGER = logging.getLogger(__name__)

# Events that mean door / trouble / output status is worth re-reading now.
_FULL_REFRESH_KINDS = {KIND_DOOR, KIND_ACCESS, KIND_TROUBLE}
# Keep this many event keys to recognise lines already seen.
_SEEN_LIMIT = 500
# Events older than this (by the controller's clock, relative to the newest line
# read) are history after an outage, not news: kept, but not sent to automations.
_STALE_SECONDS = 120

ARM_OK = "ok"
ARM_FAILED = "failed"
ARM_UNCONFIRMED = "unconfirmed"


class PinGuard:
    """Slows down PIN guessing: after ``MAX_FAILURES`` wrong PINs within
    ``WINDOW`` seconds, every PIN is refused for ``LOCKOUT`` seconds."""

    MAX_FAILURES = 5
    WINDOW = 300.0
    LOCKOUT = 300.0

    def __init__(self) -> None:
        self._failures: deque[float] = deque()
        self._locked_until = 0.0

    def check_allowed(self) -> None:
        from homeassistant.exceptions import ServiceValidationError

        if time.monotonic() < self._locked_until:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="pin_locked_out",
                translation_placeholders={"minutes": str(int(self.LOCKOUT // 60))},
            )

    def record_failure(self) -> None:
        now = time.monotonic()
        self._failures.append(now)
        while self._failures and now - self._failures[0] > self.WINDOW:
            self._failures.popleft()
        if len(self._failures) >= self.MAX_FAILURES:
            self._locked_until = now + self.LOCKOUT
            self._failures.clear()


@dataclass
class AreaInfo:
    """Static details of an area."""

    id: int
    name: str
    stay_enabled: bool = True
    instant_enabled: bool = True
    has_inputs: bool | None = None  # None = unknown (details not readable)


@dataclass
class DoorInfo:
    """Static details of a door."""

    id: int
    name: str
    has_position_input: bool = False


@dataclass
class InputInfo:
    """Static details of an input (zone)."""

    id: int
    name: str
    areas: list[int] = field(default_factory=list)
    # area id -> zone type name ("Instant", "Stay Delay", ...)
    zone_types: dict[int, str] = field(default_factory=dict)
    details_known: bool = False

    @property
    def in_use(self) -> bool:
        """An input with no area is spare. Unknown details count as in use."""
        return bool(self.areas) or not self.details_known

    def armed_in_stay(self, area_id: int) -> bool:
        """Stay-type zones are left out when an area is stay-armed."""
        return "stay" not in self.zone_types.get(area_id, "").lower()


@dataclass
class ProtegeSite:
    """Everything discovered about a controller at setup."""

    serial: str | None
    firmware: str | None
    model: str
    areas: dict[int, AreaInfo]
    doors: dict[int, DoorInfo]
    inputs: dict[int, InputInfo]
    trouble_inputs: dict[int, str]
    outputs: dict[int, str]

    def area_by_name(self, name: str) -> AreaInfo | None:
        return next((a for a in self.areas.values() if a.name == name), None)

    def door_by_name(self, name: str) -> DoorInfo | None:
        return next((d for d in self.doors.values() if d.name == name), None)

    def input_by_name(self, name: str) -> InputInfo | None:
        return next((i for i in self.inputs.values() if i.name == name), None)


@dataclass
class ProtegeState:
    """One poll of live status."""

    areas: dict[int, AreaStatus] = field(default_factory=dict)
    doors: dict[int, DoorStatus] = field(default_factory=dict)
    inputs: dict[int, InputStatus] = field(default_factory=dict)
    trouble_inputs: dict[int, InputStatus] = field(default_factory=dict)
    outputs: dict[int, OutputStatus] = field(default_factory=dict)
    health: dict[str, str] = field(default_factory=dict)
    health_troubles: list[str] = field(default_factory=list)
    event_seq: int = 0  # increases whenever new events arrive


def _valid_id(value: str | None) -> int | None:
    try:
        number = int(value or "")
    except ValueError:
        return None
    return None if number in (NO_RECORD, 4294967295) or number < 0 else number


def _flag(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() == "true"


async def _names(client: ProtegeClient, table: str) -> dict[int, str]:
    try:
        return await client.list_records(table)
    except ProtegeAuthError:
        raise
    except ProtegeError as err:
        _LOGGER.debug("Could not list %s: %s", table, err)
        return {}


async def _detail(client: ProtegeClient, table: str, rec_id: int) -> dict[str, str]:
    try:
        return await client.get_record(table, rec_id)
    except ProtegeAuthError:
        raise
    except ProtegeError as err:
        _LOGGER.debug("Could not read %s %s: %s", table, rec_id, err)
        return {}


async def async_discover(client: ProtegeClient) -> ProtegeSite:
    """Read names and the details that decide which entities make sense.

    A restricted operator may not be allowed to read programming records; every
    step falls back to the live status so the integration still works.
    """
    try:
        health = await client.health_values()
    except ProtegeAuthError:
        raise
    except ProtegeError:
        health = {}

    area_names = await _names(client, TBL_AREAS)
    door_names = await _names(client, TBL_DOORS)
    input_names = await _names(client, TBL_INPUTS)
    trouble_names = await _names(client, TBL_TROUBLE_INPUTS)
    output_names = await _names(client, TBL_OUTPUTS)
    zone_type_names = await _names(client, TBL_INPUT_TYPES)

    # Fall back to whatever the live status reports, with generic names.
    for ids, names, label in (
        (await client.area_status(), area_names, "Area"),
        (await client.door_status(), door_names, "Door"),
        (await client.input_status(), input_names, "Input"),
        (await client.trouble_input_status(), trouble_names, "Trouble input"),
        (await client.output_status(), output_names, "Output"),
    ):
        for rec_id in ids:
            names.setdefault(rec_id, f"{label} {rec_id}")

    inputs: dict[int, InputInfo] = {}
    for rec_id, name in sorted(input_names.items()):
        detail = await _detail(client, TBL_INPUTS, rec_id)
        areas: list[int] = []
        zone_types: dict[int, str] = {}
        for slot in ("1", "2", "3", "4"):
            area = _valid_id(detail.get(f"Area{slot}"))
            if area is None:
                continue
            areas.append(area)
            zone_type = _valid_id(detail.get(f"ZoneType{slot}"))
            if zone_type is not None:
                zone_types[area] = zone_type_names.get(zone_type, "")
        inputs[rec_id] = InputInfo(rec_id, name, areas, zone_types, details_known=bool(detail))

    details_known = any(info.details_known for info in inputs.values())
    areas: dict[int, AreaInfo] = {}
    for rec_id, name in sorted(area_names.items()):
        detail = await _detail(client, TBL_AREAS, rec_id)
        areas[rec_id] = AreaInfo(
            rec_id,
            name,
            stay_enabled=_flag(detail.get("EnableStayArming"), True),
            instant_enabled=_flag(detail.get("EnableInstantArming"), True),
            has_inputs=(
                any(rec_id in info.areas for info in inputs.values()) if details_known else None
            ),
        )

    doors: dict[int, DoorInfo] = {}
    for rec_id, name in sorted(door_names.items()):
        detail = await _detail(client, TBL_DOORS, rec_id)
        doors[rec_id] = DoorInfo(
            rec_id,
            name,
            has_position_input=_valid_id(detail.get("DoorPositionInput")) is not None,
        )

    return ProtegeSite(
        serial=(health.get("SerialNumber") or "").strip() or None,
        firmware=(health.get("WXVersion") or "").strip() or None,
        model="Protege WX",
        areas=areas,
        doors=doors,
        inputs=inputs,
        trouble_inputs=dict(sorted(trouble_names.items())),
        outputs=dict(sorted(output_names.items())),
    )


class ProtegeCoordinator(DataUpdateCoordinator[ProtegeState]):
    """Polls live status and the event log over the client's single session."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ProtegeClient,
        site: ProtegeSite,
    ) -> None:
        interval = entry.options.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
            always_update=False,
        )
        self.client = client
        self.site = site
        self.parser = EventParser(
            (a.name for a in site.areas.values()),
            (d.name for d in site.doors.values()),
            (i.name for i in site.inputs.values()),
            site.trouble_inputs.values(),
        )
        self._poll_outputs = bool(entry.options.get(OPT_OUTPUTS))
        self._notify_failed_arm = entry.options.get(OPT_NOTIFY_FAILED_ARM, True)
        self._last_full = 0.0
        self._last_health = 0.0
        self._seen: set[tuple] = set()
        self._seen_order: deque[tuple] = deque()
        self._events_primed = False
        self._event_seq = 0
        self.history: deque[ParsedEvent] = deque(maxlen=EVENT_HISTORY)
        self._event_listeners: list[Callable[[ParsedEvent], None]] = []
        # Who used Home Assistant to control an area: area id -> (name, time).
        self.ha_actor: dict[int, tuple[str, float]] = {}
        self.events_supported = True
        self.pin_guard = PinGuard()
        self.codes = UserCodes(dict(entry.options))
        # (monotonic time received, area name, zones) for recent arm failures.
        self.recent_failures: deque[tuple[float, str, list[str]]] = deque(maxlen=10)

    # ── event listeners ────────────────────────────────────────────────────

    @callback
    def async_add_event_listener(self, listener: Callable[[ParsedEvent], None]) -> CALLBACK_TYPE:
        """Call ``listener`` for every new, meaningful event-log line."""
        self._event_listeners.append(listener)

        @callback
        def remove() -> None:
            self._event_listeners.remove(listener)

        return remove

    def input_area_armed(self, input_id: int) -> bool:
        """Is any area this input belongs to armed, arming or in entry delay?"""
        info = self.site.inputs.get(input_id)
        if self.data is None or info is None:
            return True  # unknown: assume armed (safer)
        for area_id in info.areas or list(self.site.areas):
            status = self.data.areas.get(area_id)
            if status is None or not status.known or status.is_armed_or_arming:
                return True
        return False

    async def async_authorise_bypass(self, input_id: int, code: str | None) -> None:
        """Bypassing weakens the alarm. When PINs are set up, it needs a PIN
        allowed to disarm; without a PIN it's only allowed while disarmed."""
        from homeassistant.exceptions import ServiceValidationError

        if not self.codes.enabled:
            return
        if code:
            self.pin_guard.check_allowed()
            result = await self.hass.async_add_executor_job(self.codes.check, code, "disarm")
            if result.reason == "invalid_code":
                self.pin_guard.record_failure()
            if not result.allowed:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key=result.reason or "invalid_code",
                    translation_placeholders={"user": result.user or ""},
                )
            return
        if self.input_area_armed(input_id):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="bypass_while_armed"
            )

    def is_own_operator(self, by: str) -> bool:
        """Was this event done by the operator this integration logs in as?
        Events show the operator's display name ("Home Assistant"), which can
        differ from the login name ("homeassistant") only in case and spaces."""
        def norm(text: str) -> str:
            return "".join(text.lower().split())

        return norm(by) == norm(self.client.username)

    def last_area_event(self, area_name: str) -> ParsedEvent | None:
        for parsed in reversed(self.history):
            if parsed.kind == KIND_AREA and parsed.subject == area_name and parsed.by:
                return parsed
        return None

    # ── polling ────────────────────────────────────────────────────────────

    async def async_refresh_all(self) -> None:
        """Re-read everything now (after a command), not just areas and inputs."""
        self._last_full = 0.0
        await self.async_refresh()

    @staticmethod
    def _keys(page: list[ProtegeEvent]) -> list[tuple]:
        """Identity of each line in a page. Identical lines in the same second
        (e.g. two denied cards) are told apart by their order in the page."""
        counts: dict[tuple[str, str], int] = {}
        keys = []
        for event in page:
            base = event.key
            counts[base] = counts.get(base, 0) + 1
            keys.append((*base, counts[base]))
        return keys

    async def _read_events(self) -> list[tuple[tuple, ProtegeEvent]]:
        """Read the latest page; return the (key, event) pairs not seen yet.

        Nothing is marked as seen here: that happens only once the whole update
        has succeeded, so a failed poll can't swallow a "Failure To ARM" line.
        """
        if not self.events_supported:
            return []
        try:
            page = await self.client.events("Latest")
        except ProtegeAuthError:
            raise
        except ProtegeError as err:
            _LOGGER.debug("Event log not readable: %s", err)
            return []
        return [(key, event) for key, event in zip(self._keys(page), page, strict=True)
                if key not in self._seen]

    def _commit_events(self, fresh: list[tuple[tuple, ProtegeEvent]]) -> list[ParsedEvent]:
        """Mark lines as seen; return the meaningful ones that are news."""
        for key, _ in fresh:
            self._seen.add(key)
            self._seen_order.append(key)
        while len(self._seen_order) > _SEEN_LIMIT:
            self._seen.discard(self._seen_order.popleft())
        parsed = [self.parser.parse(event) for _, event in fresh]
        meaningful = [p for p in parsed if p.kind != KIND_NOISE]
        if not self._events_primed:
            # The first page is history, not news: keep it for context only.
            self._events_primed = True
            self.history.extend(meaningful)
            return []
        times = [p.event.time for p in meaningful if p.event.time]
        if not times:
            return meaningful
        newest = max(times)
        news = []
        for p in meaningful:
            if p.event.time and (newest - p.event.time).total_seconds() > _STALE_SECONDS:
                self.history.append(p)  # caught up after an outage: not news
            else:
                news.append(p)
        return news

    async def _async_update_data(self) -> ProtegeState:
        previous = self.data or ProtegeState()
        now = time.monotonic()
        try:
            fresh = await self._read_events()
            fresh_kinds = {self.parser.parse(event).kind for _, event in fresh}
            state = ProtegeState(
                areas=await self.client.area_status(),
                inputs=await self.client.input_status(),
                doors=previous.doors,
                trouble_inputs=previous.trouble_inputs,
                outputs=previous.outputs,
                health=previous.health,
                health_troubles=previous.health_troubles,
                event_seq=previous.event_seq,
            )
            if (
                now - self._last_full >= FULL_REFRESH_SECONDS
                or fresh_kinds & _FULL_REFRESH_KINDS
                or not previous.doors
            ):
                state.doors = await self.client.door_status()
                state.trouble_inputs = await self.client.trouble_input_status()
                if self._poll_outputs:
                    state.outputs = await self.client.output_status()
                self._last_full = now
            if now - self._last_health >= HEALTH_REFRESH_SECONDS:
                try:
                    state.health = await self.client.health_values()
                    state.health_troubles = await self.client.health_troubles()
                except ProtegeAuthError:
                    raise
                except ProtegeError as err:
                    _LOGGER.debug("Health not readable: %s", err)
                self._last_health = now
        except ProtegeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (TimeoutError, ProtegeError) as err:
            raise UpdateFailed(f"Error talking to the controller: {err}") from err

        meaningful = self._commit_events(fresh)
        if meaningful:
            self._event_seq += 1
            state.event_seq = self._event_seq
            self.hass.loop.call_soon(self._dispatch, meaningful, state)
        return state

    @callback
    def _dispatch(self, events: list[ParsedEvent], state: ProtegeState) -> None:
        for parsed in events:
            self.history.append(parsed)
            self.hass.bus.async_fire(
                EVENT_LOG,
                {
                    "entry_id": self.config_entry.entry_id,
                    "kind": parsed.kind,
                    "subject": parsed.subject,
                    "type": parsed.event_type,
                    "by": parsed.by,
                    "mode": parsed.mode,
                    "method": parsed.method,
                    "text": parsed.event.text,
                    "time": parsed.event.time.isoformat() if parsed.event.time else None,
                },
            )
            if parsed.kind == KIND_AREA and parsed.event_type == "failed_to_arm":
                self._failed_to_arm(parsed, events, state)
            for listener in list(self._event_listeners):
                try:
                    listener(parsed)
                except Exception:  # one broken listener mustn't drop the rest
                    _LOGGER.exception("Error handling Protege event %s", parsed.event.text)

    # ── arm-failure feedback ───────────────────────────────────────────────

    def _area_inputs(self, area_id: int, stay: bool):
        for info in self.site.inputs.values():
            if area_id not in info.areas and (info.details_known or not info.in_use):
                continue
            if stay and not info.armed_in_stay(area_id):
                continue
            yield info

    def open_zones(self, area_id: int, state: ProtegeState | None = None, *, stay: bool = False) -> list[str]:
        """Names of zones in an area that are open and not bypassed."""
        state = state or self.data
        names = []
        for info in self._area_inputs(area_id, stay):
            status = state.inputs.get(info.id) if state else None
            if status is not None and status.is_open and status.bypass == "none":
                names.append(info.name)
        return names

    def zones_known(self, area_id: int, *, stay: bool = False) -> bool:
        """True when every relevant zone's status is known."""
        if self.data is None:
            return False
        for info in self._area_inputs(area_id, stay):
            status = self.data.inputs.get(info.id)
            if status is None or not status.known:
                return False
        return True

    def zones_behind_failure(
        self, failure: ParsedEvent, events: list[ParsedEvent], state: ProtegeState | None = None
    ) -> list[str]:
        """Zones that stopped an arm: inputs logged as opened at the same moment,
        else the area's currently open zones."""
        same_time = [
            p.subject for p in events
            if p.kind == KIND_INPUT and p.event_type == "opened" and p.subject
            and p.event.time == failure.event.time
        ]
        if same_time:
            return same_time
        area = self.site.area_by_name(failure.subject or "")
        return self.open_zones(area.id, state) if area else []

    def _failed_to_arm(self, failure: ParsedEvent, events: list[ParsedEvent], state: ProtegeState) -> None:
        zones = self.zones_behind_failure(failure, events, state)
        self.recent_failures.append((time.monotonic(), failure.subject or "", zones))
        self.hass.bus.async_fire(
            EVENT_FAILED_TO_ARM,
            {
                "entry_id": self.config_entry.entry_id,
                "area": failure.subject,
                "by": failure.by,
                "zones": zones,
                "time": failure.event.time.isoformat() if failure.event.time else None,
            },
        )
        if self._notify_failed_arm:
            zone_text = ", ".join(zones) if zones else "a zone that was open"
            persistent_notification.async_create(
                self.hass,
                f"{failure.subject} didn't arm because {zone_text} "
                f"{'was' if len(zones) <= 1 else 'were'} open. Close it or use force arm.",
                title="Alarm didn't arm",
                notification_id=f"{DOMAIN}_failed_to_arm_{failure.subject}",
            )

    async def async_check_arm_result(
        self, area_id: int, since: float, *, stay: bool = False
    ) -> tuple[str, list[str]]:
        """After an arm command, confirm it took.

        Returns ``(ARM_OK, [])``, ``(ARM_FAILED, zones)`` or
        ``(ARM_UNCONFIRMED, [])``. ``since`` is ``time.monotonic()`` taken just
        before the command. Looks at fresh status and events for about 2 s;
        an arm is only reported as working when fresh status shows it armed
        or in its exit delay.
        """
        area = self.site.areas.get(area_id)
        name = area.name if area else ""
        attempts = 4
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(0.6)
            await self.async_refresh()
            await asyncio.sleep(0)  # let queued event dispatch run
            for received, area_name, zones in reversed(self.recent_failures):
                if received >= since and area_name == name:
                    return ARM_FAILED, zones
            if not self.last_update_success:
                continue
            status = self.data.areas.get(area_id) if self.data else None
            if status is not None and status.is_armed_or_arming:
                return ARM_OK, []
        if not self.last_update_success:
            return ARM_UNCONFIRMED, []
        return ARM_FAILED, self.open_zones(area_id, stay=stay)
