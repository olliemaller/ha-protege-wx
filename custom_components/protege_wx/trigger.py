"""Automation triggers: "When ..." building blocks for the automation editor.

Each trigger targets doors, areas or the controller (pick the device, its
area, or the entity) and fires when that device's event entity records a
matching event from the controller's event log:

* access_granted: someone badged in, optionally only certain people or only a
  card or a PIN
* access_denied: a card or PIN was refused
* door_alert: a door was forced open or left open
* failed_to_arm: an area refused to arm (the zones stopping it are included)
* emergency: a duress, panic or medical alarm

Needs Home Assistant 2026.10 or later, which added triggers that integrations
provide. On older versions this platform offers no triggers and the event
entities and protege_wx_* bus events remain the way to automate.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

# Not in homeassistant.const on every version this supports.
CONF_OPTIONS = "options"
CONF_TARGET = "target"

_LOGGER = logging.getLogger(__name__)

try:  # Home Assistant 2026.10+
    import inspect

    from homeassistant.helpers.target import (
        TargetStateChangedData,
        async_track_target_selector_state_change_event,
    )
    from homeassistant.helpers.trigger import (
        Trigger,
        TriggerActionRunner,
        TriggerConfig,
    )

    SUPPORTED = "did_not_trigger" in inspect.signature(Trigger.async_attach_runner).parameters
except ImportError:  # pragma: no cover - older Home Assistant
    SUPPORTED = False

CONF_PEOPLE = "people"
CONF_METHOD = "method"
CONF_ALERTS = "alerts"
CONF_TYPES = "types"

METHODS = ("any", "card", "pin")
DOOR_ALERTS = ("forced_open", "left_open")
EMERGENCIES = ("duress", "panic", "medical")


def event_entity_kind(hass: HomeAssistant, entity_id: str) -> str | None:
    """area, door or controller, for this integration's event entities."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != DOMAIN or entry.domain != "event":
        return None
    unique_id = entry.unique_id
    if not unique_id.endswith("_events"):
        return None
    for kind in ("door", "area", "controller"):
        if f"_{kind}_" in unique_id:
            return kind
    return None


def _target_schema(options: dict[Any, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
            vol.Optional(CONF_OPTIONS, default={}): options,
        }
    )


if SUPPORTED:

    class _EventTrigger(Trigger):
        """Fires when a targeted event entity records a matching event."""

        _kind: str  # area / door / controller
        _schema: vol.Schema = _target_schema({})

        @classmethod
        async def async_validate_config(cls, hass: HomeAssistant, config: dict[str, Any]) -> dict[str, Any]:
            return cls._schema(config)

        def __init__(self, hass: HomeAssistant, config: TriggerConfig) -> None:
            super().__init__(hass, config)
            self._target = config.target or {}
            self._options = config.options or {}

        def matches(self, event_type: str | None, attributes: dict[str, Any]) -> bool:
            raise NotImplementedError

        def describe(self, name: str, attributes: dict[str, Any]) -> str:
            return f"{name}: {attributes.get('event_type')}"

        async def async_attach_runner(
            self, run_action: TriggerActionRunner, did_not_trigger: Any = None
        ) -> CALLBACK_TYPE:
            hass = self._hass

            def entity_filter(entities: set[str]) -> set[str]:
                return {e for e in entities if event_entity_kind(hass, e) == self._kind}

            @callback
            def state_changed(data: TargetStateChangedData) -> None:
                event = data.state_change_event
                old, new = event.data["old_state"], event.data["new_state"]
                if new is None or old is None:
                    return
                if new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or old.state == STATE_UNAVAILABLE:
                    return
                if new.state == old.state and new.attributes == old.attributes:
                    return  # nothing new (two events in the same instant differ in attributes)
                attributes = dict(new.attributes)
                if not self.matches(attributes.get("event_type"), attributes):
                    return
                name = attributes.get("subject") or new.name
                run_action(
                    {
                        "entity_id": new.entity_id,
                        "event_type": attributes.get("event_type"),
                        "user": attributes.get("user"),
                        "by": attributes.get("by"),
                        "method": attributes.get("method"),
                        "subject": attributes.get("subject"),
                        "text": attributes.get("text"),
                        "from_state": old,
                        "to_state": new,
                    },
                    self.describe(str(name), attributes),
                    event.context,
                )

            remove = async_track_target_selector_state_change_event(
                hass, self._target, state_changed, entity_filter
            )
            if inspect.isawaitable(remove):  # a coroutine in 2026.10+
                remove = await remove
            return remove

    class AccessGrantedTrigger(_EventTrigger):
        _kind = "door"
        _schema = _target_schema(
            {
                vol.Optional(CONF_PEOPLE, default=[]): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(CONF_METHOD, default="any"): vol.In(METHODS),
            }
        )

        def matches(self, event_type: str | None, attributes: dict[str, Any]) -> bool:
            if event_type != "access_granted":
                return False
            people = {p.strip().casefold() for p in self._options.get(CONF_PEOPLE, []) if p.strip()}
            if people:
                who = str(attributes.get("user") or attributes.get("by") or "").casefold()
                if who not in people:
                    return False
            method = self._options.get(CONF_METHOD, "any")
            return method == "any" or attributes.get("method") == method

        def describe(self, name: str, attributes: dict[str, Any]) -> str:
            who = attributes.get("user") or attributes.get("by") or "someone"
            return f"{name}: access granted to {who}"

    class AccessDeniedTrigger(_EventTrigger):
        _kind = "door"

        def matches(self, event_type: str | None, attributes: dict[str, Any]) -> bool:
            return event_type == "access_denied"

        def describe(self, name: str, attributes: dict[str, Any]) -> str:
            return f"{name}: access denied"

    class DoorAlertTrigger(_EventTrigger):
        _kind = "door"
        _schema = _target_schema(
            {
                vol.Optional(CONF_ALERTS, default=list(DOOR_ALERTS)): vol.All(
                    cv.ensure_list, [vol.In(DOOR_ALERTS)], vol.Length(min=1)
                ),
            }
        )

        def matches(self, event_type: str | None, attributes: dict[str, Any]) -> bool:
            return event_type in self._options.get(CONF_ALERTS, DOOR_ALERTS)

        def describe(self, name: str, attributes: dict[str, Any]) -> str:
            what = "forced open" if attributes.get("event_type") == "forced_open" else "left open"
            return f"{name}: {what}"

    class FailedToArmTrigger(_EventTrigger):
        _kind = "area"

        def matches(self, event_type: str | None, attributes: dict[str, Any]) -> bool:
            return event_type == "failed_to_arm"

        def describe(self, name: str, attributes: dict[str, Any]) -> str:
            return f"{name}: failed to arm"

    class EmergencyTrigger(_EventTrigger):
        _kind = "controller"
        _schema = _target_schema(
            {
                vol.Optional(CONF_TYPES, default=list(EMERGENCIES)): vol.All(
                    cv.ensure_list, [vol.In(EMERGENCIES)], vol.Length(min=1)
                ),
            }
        )

        def matches(self, event_type: str | None, attributes: dict[str, Any]) -> bool:
            return event_type in self._options.get(CONF_TYPES, EMERGENCIES)

        def describe(self, name: str, attributes: dict[str, Any]) -> str:
            return f"{attributes.get('event_type')} alarm"

    TRIGGERS: dict[str, type[Trigger]] = {
        "access_granted": AccessGrantedTrigger,
        "access_denied": AccessDeniedTrigger,
        "door_alert": DoorAlertTrigger,
        "failed_to_arm": FailedToArmTrigger,
        "emergency": EmergencyTrigger,
    }
else:  # pragma: no cover - older Home Assistant
    TRIGGERS = {}


async def async_get_triggers(hass: HomeAssistant) -> dict[str, Any]:
    """Return the triggers this integration provides."""
    return TRIGGERS
