"""Behaviour added in 0.8.3: actions set up once, visitor re-lock safety,
an optional PIN for unlocking, poll tolerance and the per-entry PIN guard."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from aioprotegewx import ProtegeConnectionError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.protege_wx.const import DOMAIN
from custom_components.protege_wx.users import make_user

from .test_coverage import no_details  # noqa: F401 - fixture
from .test_integration import (  # noqa: F401 - fixtures
    ALARM,
    _door_commands,
    _entry,
    _setup,
    _state,
    controller,
    fast_retries,
)

LOCK = "lock.front_door"


async def _broken(*_args, **_kwargs):
    raise ProtegeConnectionError("busy")


async def _tick(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


# ── actions ─────────────────────────────────────────────────────────────────


async def test_actions_exist_without_a_loaded_entry(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    for action in ("arm", "arm_when_ready", "set_user_enabled", "unlock_door",
                   "visitor_unlock", "bypass", "pulse_output"):
        assert hass.services.has_service(DOMAIN, action)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "arm")  # still registered
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "arm", {"entity_id": ALARM, "mode": "away"}, blocking=True
        )
    assert err.value.translation_key == "not_loaded"
    assert not controller.state.commands


# ── visitor unlock ──────────────────────────────────────────────────────────


async def test_failed_relocks_raise_and_clear_a_repair(hass: HomeAssistant, controller, monkeypatch) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    await hass.services.async_call(DOMAIN, "visitor_unlock", {"entity_id": LOCK, "minutes": 1}, blocking=True)
    client = entry.runtime_data.client
    working = client.lock_door
    monkeypatch.setattr(client, "lock_door", _broken)
    issue_id = f"visitor_relock_failed_{entry.entry_id}_0"
    registry = ir.async_get(hass)
    await _tick(hass, 65)  # first try at the end of the minute
    await _tick(hass, 100)
    assert registry.async_get_issue(DOMAIN, issue_id) is None  # two failures: not yet
    await _tick(hass, 135)
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_placeholders["door"] == "Front Door"
    monkeypatch.setattr(client, "lock_door", working)
    await _tick(hass, 170)
    assert registry.async_get_issue(DOMAIN, issue_id) is None
    assert entry.runtime_data.visitors.until.get(0) is None
    assert _door_commands(controller)[-1] == 0


async def test_unload_locks_a_visitor_door(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    await hass.services.async_call(DOMAIN, "visitor_unlock", {"entity_id": LOCK}, blocking=True)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _door_commands(controller) == [2, 0]  # locked now, not in 15 minutes


async def test_unload_that_cannot_lock_leaves_it_to_the_next_setup(
    hass: HomeAssistant, controller, monkeypatch
) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    await hass.services.async_call(DOMAIN, "visitor_unlock", {"entity_id": LOCK}, blocking=True)
    monkeypatch.setattr(entry.runtime_data.client, "lock_door", _broken)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _door_commands(controller) == [2]
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _tick(hass, 5)  # due straight away, not at the original end
    assert _door_commands(controller) == [2, 0]


async def test_removed_entry_hands_its_relock_to_the_next_one(
    hass: HomeAssistant, controller, monkeypatch
) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    await hass.services.async_call(DOMAIN, "visitor_unlock", {"entity_id": LOCK}, blocking=True)
    monkeypatch.setattr(entry.runtime_data.client, "lock_door", _broken)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _door_commands(controller) == [2]
    assert not [k for k in hass.data.get(DOMAIN, {}) if isinstance(k, tuple) and entry.entry_id in k]
    again = _entry(controller)  # the same controller added back
    await _setup(hass, again)
    await _tick(hass, 5)
    assert _door_commands(controller) == [2, 0]


# ── PIN for unlocking ───────────────────────────────────────────────────────


async def test_unlock_needs_no_pin_by_default(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, users=[make_user("Alex", "1234")])
    await _setup(hass, entry)
    assert hass.states.get(LOCK).attributes.get("code_format") is None
    await hass.services.async_call("lock", "unlock", {"entity_id": LOCK}, blocking=True)
    assert _door_commands(controller) == [1]


async def test_unlock_pin_when_turned_on(hass: HomeAssistant, controller) -> None:
    users = [make_user("Alex", "1234"), make_user("Cleaner", "5555", can_disarm=False)]
    entry = _entry(controller, users=users, code_unlock_required=True)
    await _setup(hass, entry)
    assert hass.states.get(LOCK).attributes["code_format"] == r"^\d*$"
    for data, reason in (({}, "no_code"), ({"code": "0000"}, "invalid_code"),
                         ({"code": "5555"}, "not_permitted")):
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call("lock", "unlock", {"entity_id": LOCK, **data}, blocking=True)
        assert err.value.translation_key == reason
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "visitor_unlock", {"entity_id": LOCK}, blocking=True)
    assert err.value.translation_key == "no_code"
    for domain, service, target in (("switch", "turn_on", "switch.front_door_hold_open"),
                                    ("button", "press", "button.front_door_visitor_unlock")):
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(domain, service, {"entity_id": target}, blocking=True)
        assert err.value.translation_key == "unlock_needs_pin"
    assert not _door_commands(controller)
    await hass.services.async_call("lock", "unlock", {"entity_id": LOCK, "code": "1234"}, blocking=True)
    await hass.services.async_call(
        DOMAIN, "unlock_door", {"entity_id": LOCK, "hold_open": True, "code": "1234"}, blocking=True
    )
    await hass.services.async_call("lock", "lock", {"entity_id": LOCK}, blocking=True)  # no PIN to lock
    assert _door_commands(controller) == [1, 2, 0]


# ── PIN guard ───────────────────────────────────────────────────────────────


async def test_all_areas_counts_a_wrong_pin_once(hass: HomeAssistant, no_details) -> None:  # noqa: F811
    entry = _entry(no_details, users=[make_user("Alex", "1234")])
    await _setup(hass, entry)
    all_areas = next(
        s.entity_id for s in hass.states.async_all("alarm_control_panel")
        if s.entity_id not in (ALARM, "alarm_control_panel.system_area")
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "alarm_control_panel", "alarm_arm_away", {"entity_id": all_areas, "code": "0000"}, blocking=True
        )
    assert len(entry.runtime_data.coordinator.pin_guard._failures) == 1
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": all_areas, "code": "1234"}, blocking=True
    )
    assert _state(hass, all_areas) == "armed_away"


async def test_pin_lockout_survives_a_reload(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, users=[make_user("Alex", "1234")])
    await _setup(hass, entry)
    for _ in range(5):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "alarm_control_panel", "alarm_disarm", {"entity_id": ALARM, "code": "0000"}, blocking=True
            )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "alarm_control_panel", "alarm_disarm", {"entity_id": ALARM, "code": "1234"}, blocking=True
        )
    assert err.value.translation_key == "pin_locked_out"
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ("pin_guard", entry.entry_id) not in hass.data.get(DOMAIN, {})


# ── smaller fixes ───────────────────────────────────────────────────────────


async def test_failed_to_arm_notification_is_per_entry(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.state.events.append("Sun 25/10/2026 19:30:00 Area Alarm Failure To ARM By User Jane Citizen")
    with patch(
        "custom_components.protege_wx.coordinator.persistent_notification.async_create"
    ) as create:
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
    ids = [call.kwargs["notification_id"] for call in create.call_args_list]
    assert f"{DOMAIN}_failed_to_arm_{entry.entry_id}_Alarm" in ids
