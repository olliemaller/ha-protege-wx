"""Behaviour added in 0.9.0: the lockdown action, and outputs found on the
controller without being chosen in the options."""
from __future__ import annotations

import pytest
from aioprotegewx import ProtegeConnectionError
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.protege_wx.const import DOMAIN, EVENT_LOGBOOK

from .test_integration import (  # noqa: F401 - fixtures
    _device,
    _entry,
    _setup,
    _state,
    controller,
    fast_retries,
)

BELL = "switch.protege_wx_controller_controller_bell_0"


# ── lockdown ────────────────────────────────────────────────────────────────


async def test_lockdown_locks_every_door_and_logs(
    hass: HomeAssistant, controller, hass_admin_user
) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    await hass.services.async_call(
        DOMAIN, "unlock_door", {"entity_id": "lock.front_door", "hold_open": True}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "visitor_unlock", {"entity_id": "lock.gate", "minutes": 5}, blocking=True
    )
    assert _state(hass, "lock.front_door") == "unlocked"
    assert entry.runtime_data.visitors.until.get(1)
    logbook = async_capture_events(hass, EVENT_LOGBOOK)

    await hass.services.async_call(
        DOMAIN, "lockdown", {}, blocking=True, context=Context(user_id=hass_admin_user.id)
    )
    await hass.async_block_till_done()
    assert _state(hass, "lock.front_door") == "locked"
    assert _state(hass, "lock.gate") == "locked"
    assert not entry.runtime_data.visitors.until  # no visitor relock left pending
    assert [e.data["message"] for e in logbook if "lockdown" in e.data["message"]] == [
        f"lockdown by {hass_admin_user.name}: locked 2 door(s)"
    ]


async def test_lockdown_is_for_admins_only(hass: HomeAssistant, controller, hass_read_only_user) -> None:
    await _setup(hass, _entry(controller))
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN, "lockdown", {}, blocking=True, context=Context(user_id=hass_read_only_user.id)
        )
    assert not [c for c in controller.state.commands if "GXT_DOORS_TBL" in c]


async def test_lockdown_carries_on_past_a_failed_door(
    hass: HomeAssistant, controller, monkeypatch
) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    client = entry.runtime_data.client
    working = client.lock_door

    async def lock_door(door_id: int) -> None:
        if door_id == 0:
            raise ProtegeConnectionError("busy")
        await working(door_id)

    monkeypatch.setattr(client, "lock_door", lock_door)
    logbook = async_capture_events(hass, EVENT_LOGBOOK)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "lockdown", {}, blocking=True)
    assert err.value.translation_key == "lockdown_failed"
    assert err.value.translation_placeholders == {"doors": "Front Door"}
    assert "Command=0" in [c for c in controller.state.commands if "RecId=1" in c][-1]
    await hass.async_block_till_done()
    assert any(
        e.data["message"] == "lockdown by an automation: locked 1 door(s); didn't lock Front Door"
        for e in logbook
    )


async def test_lockdown_without_a_loaded_controller(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "lockdown", {}, blocking=True)
    assert err.value.translation_key == "not_loaded"


# ── outputs found on the controller ─────────────────────────────────────────


async def test_found_outputs_start_disabled_on_the_controller(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, outputs=["120"])
    await _setup(hass, entry)
    registry = er.async_get(hass)
    bell = registry.async_get(BELL)
    assert bell is not None and bell.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert bell.device_id == _device(hass, "A1B2C3D4").id  # no device of its own
    assert _device(hass, "A1B2C3D4_output_112") is None
    assert _state(hass, "switch.garage_door_open_close") == "off"  # the chosen one still works


async def test_enabled_found_output_is_polled_and_switched(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    # Turned on by the user before setup, as after enabling it and the reload.
    registry.async_get_or_create(
        "switch", DOMAIN, "A1B2C3D4_output_112", config_entry=entry,
        suggested_object_id="protege_wx_controller_controller_bell_0",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.coordinator.async_refresh()  # the next poll reads outputs
    await hass.async_block_till_done()
    assert _state(hass, BELL) == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": BELL}, blocking=True)
    assert _state(hass, BELL) == "on"
    assert hass.states.get(BELL).name == "Protege WX controller Controller Bell 0"
