"""Areas as alarm control panels."""
from __future__ import annotations

import time
from typing import Any

import voluptuous as vol
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ProtegeConfigEntry
from .const import DOMAIN, OPT_SHOW_ARMING
from .coordinator import ARM_FAILED, ARM_OK, AreaInfo, ProtegeCoordinator
from .entity import ProtegeEntity
from .users import UserCodes
from .wxapi.events import KIND_AREA, ParsedEvent

PARALLEL_UPDATES = 1

SERVICE_ARM = "arm"
ARM_MODES = ("away", "stay", "instant")
# A Home Assistant user is credited for controller events within this window.
_ACTOR_WINDOW = 15.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    codes = data.coordinator.codes
    show_arming = entry.options.get(OPT_SHOW_ARMING, False)
    entities = [
        ProtegeArea(data.coordinator, area, codes, show_arming)
        for area in data.site.areas.values()
    ]
    data.areas = {entity.rec_id: entity for entity in entities}
    async_add_entities(entities)
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ARM,
        {
            vol.Required("mode"): vol.In(ARM_MODES),
            vol.Optional("force", default=False): cv.boolean,
            vol.Optional("code"): cv.string,
        },
        "async_service_arm",
    )


class ProtegeArea(ProtegeEntity, AlarmControlPanelEntity):
    """A Protege area."""

    _attr_name = None

    def __init__(
        self,
        coordinator: ProtegeCoordinator,
        area: AreaInfo,
        codes: UserCodes,
        show_arming: bool,
    ) -> None:
        super().__init__(coordinator, "area", area.id, own_device=True)
        self.area = area
        self._codes = codes
        self._show_arming = show_arming
        # Areas with no inputs (e.g. the "System Area" that only carries
        # troubles) start disabled; they can be enabled by hand.
        self._attr_entity_registry_enabled_default = area.has_inputs is not False
        features = AlarmControlPanelEntityFeature.ARM_AWAY
        if area.stay_enabled:
            features |= AlarmControlPanelEntityFeature.ARM_HOME
        if area.instant_enabled:
            features |= AlarmControlPanelEntityFeature.ARM_NIGHT
        self._attr_supported_features = features
        if codes.enabled:
            self._attr_code_format = CodeFormat.NUMBER
            self._attr_code_arm_required = codes.arm_requires_code
        else:
            self._attr_code_format = None
            self._attr_code_arm_required = False
        self._changed_by: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = self.coordinator.last_area_event(self.area.name)
        if last is not None:
            self._changed_by = self._credit(last)
        self.async_on_remove(self.coordinator.async_add_event_listener(self._on_event))

    def _credit(self, parsed: ParsedEvent) -> str | None:
        """Who to show as having changed the area. Actions by this integration's
        own operator are credited to the Home Assistant user whose PIN was used."""
        by = parsed.by
        actor = self.coordinator.ha_actor.get(self.rec_id)
        if (
            by
            and self.coordinator.is_own_operator(by)
            and actor
            and time.monotonic() - actor[1] < _ACTOR_WINDOW
        ):
            return actor[0]
        return by

    @callback
    def _on_event(self, parsed: ParsedEvent) -> None:
        if (
            parsed.kind == KIND_AREA
            and parsed.subject == self.area.name
            and parsed.by
            and parsed.event_type in ("armed", "arming_started", "disarmed", "arming_cancelled")
        ):
            self._changed_by = self._credit(parsed)
            self.async_write_ha_state()

    @property
    def changed_by(self) -> str | None:
        return self._changed_by

    @property
    def _status(self):
        return self.coordinator.data.areas.get(self.rec_id)

    @property
    def available(self) -> bool:
        status = self._status
        return super().available and status is not None and status.known

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        status = self._status
        if status is None or not status.known:
            return None
        if status.in_alarm:
            return AlarmControlPanelState.TRIGGERED
        if status.state == "exit_delay":
            # Apple Home (via the HomeKit Bridge) shows every "arming" state as
            # Away, so by default report the mode being armed instead. The
            # controller already sets the stay/instant flags during the delay.
            if self._show_arming:
                return AlarmControlPanelState.ARMING
            return self._armed_mode(status)
        if status.state == "disarm_delay":
            return AlarmControlPanelState.DISARMING
        if status.state in ("entry_delay", "code_delay"):
            return AlarmControlPanelState.PENDING
        if status.state == "armed":
            return self._armed_mode(status)
        return AlarmControlPanelState.DISARMED  # 0, or 1-5 = disarmed, not ready

    @staticmethod
    def _armed_mode(status) -> AlarmControlPanelState:
        if "partial_armed" in status.flags:
            return AlarmControlPanelState.ARMED_HOME
        if "instant_armed" in status.flags:
            return AlarmControlPanelState.ARMED_NIGHT
        return AlarmControlPanelState.ARMED_AWAY

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._status
        if status is None:
            return {}
        attributes: dict[str, Any] = {
            "controller_state": status.state,
            "exit_delay": status.state == "exit_delay",
            "flags": sorted(status.flags),
            "alarms_in_memory": "alarms_in_memory" in status.flags,
        }
        if status.not_ready:
            attributes["open_zones"] = self.coordinator.open_zones(self.rec_id)
        return attributes

    # ── commands ───────────────────────────────────────────────────────────

    async def _authorise(self, code: str | None, action: str) -> str | None:
        """Check the code; return the user's name (or None if codes are off)."""
        self.coordinator.pin_guard.check_allowed()
        result = await self.hass.async_add_executor_job(self._codes.check, code, action)
        if result.reason == "invalid_code":
            self.coordinator.pin_guard.record_failure()
        if not result.allowed:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=result.reason or "invalid_code",
                translation_placeholders={"user": result.user or ""},
            )
        if result.user:
            self.coordinator.ha_actor[self.rec_id] = (result.user, time.monotonic())
        return result.user

    async def _arm_now(self, mode: str, force: bool) -> None:
        started = time.monotonic()
        await self._send(self.coordinator.client.arm_area(self.rec_id, mode, force=force))
        result, zones = await self.coordinator.async_check_arm_result(
            self.rec_id, started, stay=mode == "stay"
        )
        if result == ARM_OK:
            return
        if result == ARM_FAILED and zones:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="failed_to_arm",
                translation_placeholders={"area": self.area.name, "zones": ", ".join(zones)},
            )
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="failed_to_arm_unknown" if result == ARM_FAILED else "arm_unconfirmed",
            translation_placeholders={"area": self.area.name},
        )

    async def _arm(self, mode: str, force: bool, code: str | None) -> None:
        if mode == "stay" and force:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="force_stay_unsupported"
            )
        await self._authorise(code, "arm")
        await self._arm_now(mode, force)

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        await self._authorise(code, "disarm")
        await self._command(self.coordinator.client.disarm_area(self.rec_id))

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._arm("away", False, code)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        await self._arm("stay", False, code)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        await self._arm("instant", False, code)

    async def async_service_arm(self, mode: str, force: bool = False, code: str | None = None) -> None:
        """The protege_wx.arm action: arm in a mode, optionally forcing."""
        await self._arm(mode, force, code)

    async def async_force_arm(self, mode: str) -> None:
        """Used by the force-arm buttons. Buttons can't carry a code, and arming
        (never disarming) is what they do."""
        await self._arm_now(mode, True)

    async def async_silence(self) -> None:
        await self._command(self.coordinator.client.silence_area(self.rec_id))
