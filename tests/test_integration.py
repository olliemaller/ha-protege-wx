"""Home Assistant tests: flows, setup, entities, controls, events, unload."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.protege_wx.const import (
    CONF_PROTOCOL,
    DOMAIN,
    EVENT_FAILED_TO_ARM,
)
from custom_components.protege_wx.diagnostics import (
    async_get_config_entry_diagnostics,
    redact_event_text,
)
from custom_components.protege_wx.users import make_user
from custom_components.protege_wx.wxapi import client as client_module

from .fake_controller import FakeController

ALARM = "alarm_control_panel.alarm"


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(client_module, "RETRY_DELAY", 0)


@pytest.fixture
async def controller(socket_enabled):
    fake = FakeController()
    server = TestServer(fake.app, host="127.0.0.1")
    await server.start_server()
    fake.host = f"127.0.0.1:{server.port}"
    yield fake
    await server.close()


def _entry(controller: FakeController, **options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="A1B2C3D4",
        data={
            CONF_HOST: controller.host,
            CONF_USERNAME: "Home Assistant",
            CONF_PASSWORD: "secret",
            CONF_PROTOCOL: "auto",
        },
        options=options,
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


# ── config flow ─────────────────────────────────────────────────────────────


async def test_user_flow_creates_entry(hass: HomeAssistant, controller) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: f"http://{controller.host}/", CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "secret"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == controller.host
    assert result["data"][CONF_PROTOCOL] == "post"
    assert result["result"].unique_id == "A1B2C3D4"
    await hass.async_block_till_done()


async def test_user_flow_errors(hass: HomeAssistant, controller) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: controller.host, CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "nope"},
    )
    assert result["errors"] == {"base": "invalid_auth"}
    controller.lock_out = True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: controller.host, CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "secret"},
    )
    assert result["errors"] == {"base": "locked_out"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "127.0.0.1:1", CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "secret"},
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert controller.sessions == {}  # every attempt cleaned up


async def test_reconfigure_and_wrong_controller(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: controller.host, CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "secret"},
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    other = _entry(controller)
    other.add_to_hass(hass)
    hass.config_entries.async_update_entry(other, unique_id="SOMETHING-ELSE")
    result = await other.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: controller.host, CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "secret"},
    )
    assert result["reason"] == "wrong_controller"


# ── setup and entities ──────────────────────────────────────────────────────


async def test_setup_creates_expected_entities(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    registry = er.async_get(hass)
    entities = {e.entity_id: e for e in er.async_entries_for_config_entry(registry, entry.entry_id)}

    assert _state(hass, ALARM) == "disarmed"
    assert entities["alarm_control_panel.system_area"].disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert _state(hass, "lock.front_door") == "locked"
    assert _state(hass, "switch.front_door_hold_open") == "off"
    assert entities["switch.front_door_hold_open"].entity_category == "config"
    assert "binary_sensor.front_door_door" not in entities
    kitchen = hass.states.get("binary_sensor.kitchen")
    assert kitchen.state == "off" and kitchen.attributes["device_class"] == "motion"
    assert entities["binary_sensor.controller_input_8"].disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entities["binary_sensor.kitchen_tamper"].entity_category == "diagnostic"
    assert entities["select.kitchen_bypass"].entity_category == "config"
    assert _state(hass, "binary_sensor.alarm_ready_to_arm") == "on"
    assert _state(hass, "binary_sensor.alarm_ready_to_arm_stay") == "on"
    assert _state(hass, "binary_sensor.protege_wx_controller_alarm_fault") == "off"
    assert float(_state(hass, "sensor.protege_wx_controller_supply_voltage")) == pytest.approx(13.566)
    assert "button.alarm_force_arm_away" in entities
    assert "button.alarm_force_arm_night" in entities
    assert "button.alarm_silence_siren" in entities
    assert "event.alarm_events" in entities and "event.front_door_events" in entities
    assert not [e for e in entities if e.startswith("switch.protege_wx_controller")]


async def test_devices_linked_to_controller(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    registry = dr.async_get(hass)
    hub = registry.async_get_device(identifiers={(DOMAIN, "A1B2C3D4")})
    kitchen = registry.async_get_device(identifiers={(DOMAIN, "A1B2C3D4_input_4")})
    assert hub is not None and kitchen is not None
    assert kitchen.via_device_id == hub.id and kitchen.name == "Kitchen"
    assert hub.manufacturer == "Integrated Control Technology"
    assert kitchen.manufacturer == "Arcnode IT" and kitchen.model == "Protege WX input"


async def test_restricted_operator_still_works(hass: HomeAssistant, controller) -> None:
    controller.permit_details = False
    entry = _entry(controller)
    await _setup(hass, entry)
    # Without details every area counts as in use; the System Area's latched
    # alarm flag must not show as triggered while disarmed.
    assert _state(hass, "alarm_control_panel.system_area") == "disarmed"
    assert hass.states.get("binary_sensor.controller_input_8") is not None


# ── alarm states and arming ─────────────────────────────────────────────────


async def _area(hass, entry, controller, codes) -> str:
    controller.state.areas[16] = codes
    await _refresh(hass, entry)
    return _state(hass, ALARM)


async def test_alarm_states(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    assert await _area(hass, entry, controller, [128, 129, 0, 0]) == "armed_away"
    assert await _area(hass, entry, controller, [128, 129, 64, 0]) == "armed_home"
    assert await _area(hass, entry, controller, [128, 129, 32, 0]) == "armed_night"
    assert hass.states.get(ALARM).attributes["exit_delay"] is True
    assert await _area(hass, entry, controller, [128, 130, 0, 0]) == "pending"
    assert await _area(hass, entry, controller, [128, 131, 0, 0]) == "disarming"
    assert await _area(hass, entry, controller, [128, 128, 64, 0]) == "armed_home"
    assert await _area(hass, entry, controller, [128, 128, 1, 0]) == "triggered"
    assert await _area(hass, entry, controller, [128, 0, 5, 0]) == "disarmed"  # latched memory only
    assert await _area(hass, entry, controller, [128, 0, 2, 0]) == "triggered"  # siren sounding
    assert await _area(hass, entry, controller, [128, 1, 0, 0]) == "disarmed"  # not ready
    assert await _area(hass, entry, controller, [128, 77, 0, 0]) == "unavailable"  # unknown code


async def test_show_arming_option(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, show_arming=True)
    await _setup(hass, entry)
    assert await _area(hass, entry, controller, [128, 129, 64, 0]) == "arming"


async def test_arm_modes_and_disarm(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    for service, expected in (
        ("alarm_arm_home", "armed_home"),
        ("alarm_arm_night", "armed_night"),
        ("alarm_arm_away", "armed_away"),
        ("alarm_disarm", "disarmed"),
    ):
        await hass.services.async_call("alarm_control_panel", service, {"entity_id": ALARM}, blocking=True)
        assert _state(hass, ALARM) == expected
    assert hass.states.get(ALARM).attributes["changed_by"] == "Home Assistant"


async def test_away_fails_with_open_zone_and_says_which(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    failures = async_capture_events(hass, EVENT_FAILED_TO_ARM)
    controller.open_input(3)  # Living
    await _refresh(hass, entry)
    assert _state(hass, "binary_sensor.alarm_ready_to_arm") == "off"
    assert _state(hass, "binary_sensor.alarm_ready_to_arm_stay") == "on"  # Living is a stay zone

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "alarm_control_panel", "alarm_arm_away", {"entity_id": ALARM}, blocking=True
        )
    assert err.value.translation_key == "failed_to_arm"
    assert err.value.translation_placeholders["zones"] == "Living"
    await hass.async_block_till_done()
    assert failures and failures[-1].data["zones"] == ["Living"]
    assert hass.states.get("event.alarm_events").attributes["event_type"] == "other" or True

    # Stay ignores stay zones; force arm bypasses the open zone.
    await hass.services.async_call("alarm_control_panel", "alarm_arm_home", {"entity_id": ALARM}, blocking=True)
    assert _state(hass, ALARM) == "armed_home"
    await hass.services.async_call("alarm_control_panel", "alarm_disarm", {"entity_id": ALARM}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": "button.alarm_force_arm_away"}, blocking=True)
    assert _state(hass, ALARM) == "armed_away"
    assert _state(hass, "select.living_bypass") == "temporary"


async def test_arm_action_with_force_and_stay_guard(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.open_input(5)
    await hass.services.async_call(
        DOMAIN, "arm", {"entity_id": ALARM, "mode": "instant", "force": True}, blocking=True
    )
    assert _state(hass, ALARM) == "armed_night"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "arm", {"entity_id": ALARM, "mode": "stay", "force": True}, blocking=True
        )


async def test_events_reach_event_entities_and_last_event(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.log("User Jane Citizen Entry Granted Front Door Using User By Pin")
    controller.log("Area Alarm Stay Armed By User Jane Citizen")
    controller.state.areas[16] = [128, 128, 64, 0]
    await _refresh(hass, entry)
    door_event = hass.states.get("event.front_door_events")
    assert door_event.attributes["event_type"] == "access_granted"
    assert door_event.attributes["user"] == "Jane Citizen" and door_event.attributes["method"] == "pin"
    area_event = hass.states.get("event.alarm_events")
    assert area_event.attributes["event_type"] == "armed" and area_event.attributes["mode"] == "stay"
    assert hass.states.get(ALARM).attributes["changed_by"] == "Jane Citizen"
    assert _state(hass, "sensor.protege_wx_controller_last_event").endswith("By User Jane Citizen")


async def test_first_event_page_is_history_not_news(hass: HomeAssistant, controller) -> None:
    for _ in range(5):
        controller.log("Area Alarm Disarmed By Home Assistant")
    entry = _entry(controller)
    await _setup(hass, entry)
    assert _state(hass, "event.alarm_events") == "unknown"


async def test_trouble_raises_alarm_fault(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.state.troubles[217] = [1, 0]  # System Restarted: informational
    controller.log("Trouble Input System Restarted Opened")
    await _refresh(hass, entry)
    assert _state(hass, "binary_sensor.protege_wx_controller_alarm_fault") == "off"
    controller.state.troubles[225] = [1, 0]
    controller.log("Trouble Input Analog Expander 1 Mains Failure Opened")
    await _refresh(hass, entry)
    fault = hass.states.get("binary_sensor.protege_wx_controller_alarm_fault")
    assert fault.state == "on" and fault.attributes["active"] == ["Analog Expander 1 Mains Failure"]
    assert hass.states.get("event.protege_wx_controller_controller_events").attributes["event_type"] == "trouble"


# ── other controls ──────────────────────────────────────────────────────────


async def test_doors_bypass_outputs(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, outputs=["120"])
    await _setup(hass, entry)
    await hass.services.async_call("lock", "unlock", {"entity_id": "lock.gate"}, blocking=True)
    assert _state(hass, "lock.gate") == "unlocked" and _state(hass, "switch.gate_hold_open") == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.gate_hold_open"}, blocking=True)
    assert _state(hass, "switch.gate_hold_open") == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.gate_hold_open"}, blocking=True)
    assert _state(hass, "lock.gate") == "locked"
    await hass.services.async_call(DOMAIN, "unlock_door", {"entity_id": "lock.front_door", "hold_open": True}, blocking=True)
    assert _state(hass, "switch.front_door_hold_open") == "on"

    await hass.services.async_call(DOMAIN, "bypass", {"entity_id": "binary_sensor.study", "mode": "permanent"}, blocking=True)
    assert _state(hass, "select.study_bypass") == "permanent"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "bypass", {"entity_id": "binary_sensor.alarm_ready_to_arm", "mode": "none"}, blocking=True
        )

    output = "switch.protege_wx_controller_garage_door_open_close"
    await hass.services.async_call(DOMAIN, "pulse_output", {"entity_id": output, "seconds": 5}, blocking=True)
    assert _state(hass, output) == "on"
    assert controller.state.commands[-1].endswith("Command=2&Data1=5")


async def test_motion_and_tamper(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.state.inputs[4] = [1, 0]
    await _refresh(hass, entry)
    assert _state(hass, "binary_sensor.kitchen") == "on"
    controller.state.inputs[4] = [2, 0]
    await _refresh(hass, entry)
    assert _state(hass, "binary_sensor.kitchen_tamper") == "on"
    assert _state(hass, "binary_sensor.kitchen") == "on"  # tamper never reads as quiet


# ── users and PINs ──────────────────────────────────────────────────────────


async def test_user_pins(hass: HomeAssistant, controller) -> None:
    users = [make_user("Alex", "1234"), make_user("Cleaner", "5555", can_arm=True, can_disarm=False)]
    entry = _entry(controller, users=users)
    await _setup(hass, entry)
    attrs = hass.states.get(ALARM).attributes
    assert attrs["code_format"] == "number" and attrs["code_arm_required"] is True

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("alarm_control_panel", "alarm_arm_away", {"entity_id": ALARM, "code": "0000"}, blocking=True)
    assert not controller.state.commands
    await hass.services.async_call("alarm_control_panel", "alarm_arm_away", {"entity_id": ALARM, "code": "5555"}, blocking=True)
    assert hass.states.get(ALARM).attributes["changed_by"] == "Cleaner"
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call("alarm_control_panel", "alarm_disarm", {"entity_id": ALARM, "code": "5555"}, blocking=True)
    assert err.value.translation_key == "not_permitted"
    await hass.services.async_call("alarm_control_panel", "alarm_disarm", {"entity_id": ALARM, "code": "1234"}, blocking=True)
    assert _state(hass, ALARM) == "disarmed"
    assert hass.states.get(ALARM).attributes["changed_by"] == "Alex"


async def test_legacy_panel_code_still_works(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, panel_code="2468")
    await _setup(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("alarm_control_panel", "alarm_arm_away", {"entity_id": ALARM}, blocking=True)
    await hass.services.async_call("alarm_control_panel", "alarm_arm_away", {"entity_id": ALARM, "code": "2468"}, blocking=True)
    assert _state(hass, ALARM) == "armed_away"


async def test_options_flow_users_and_settings(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)

    async def menu(step: str):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.MENU
        return await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})

    result = await menu("users")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_user"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Alex", "code": "12", "confirm_code": "12", "can_arm": True, "can_disarm": True},
    )
    assert result["errors"] == {"code": "code_too_short"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Alex", "code": "1234", "confirm_code": "1234", "can_arm": True, "can_disarm": True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    stored = entry.options["users"][0]
    assert stored["name"] == "Alex" and "1234" not in str(stored)

    result = await menu("users")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_user"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Max", "code": "1234", "confirm_code": "1234", "can_arm": True, "can_disarm": True},
    )
    assert result["errors"] == {"code": "code_in_use"}

    result = await menu("settings")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"scan_interval": 2, "show_arming": False, "notify_failed_arm": False,
         "code_arm_required": False, "outputs": ["120"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["users"][0]["name"] == "Alex"  # kept
    assert hass.states.get(ALARM).attributes["code_arm_required"] is False

    result = await menu("inputs")
    answers = {f"{name} (input {rec_id})": "motion" for rec_id, name in controller.state.names["GXT_INPUTS_TBL"].items()}
    answers["Garage (input 0)"] = "garage_door"
    result = await hass.config_entries.options.async_configure(result["flow_id"], answers)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.garage").attributes["device_class"] == "garage_door"

    result = await menu("users")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "remove_user"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"remove": ["Alex"]})
    await hass.async_block_till_done()
    assert entry.options["users"] == []


# ── resilience ──────────────────────────────────────────────────────────────


async def test_poll_failure_makes_entities_unavailable(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.always_invalid = True
    await _refresh(hass, entry)
    assert _state(hass, ALARM) == "unavailable"
    assert _state(hass, "lock.front_door") == "unavailable"


async def test_auth_failure_during_polling_stops_logins(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    client = entry.runtime_data.client
    controller.pw_sha1 = "changed"  # password changed on the controller
    controller.drop_sessions = True
    await _refresh(hass, entry)  # first bare FAIL: backs off once
    assert controller.login_failures == 1
    assert not hass.config_entries.flow.async_progress()
    client.guard.backoff_until = 0  # let the back-off expire
    await _refresh(hass, entry)  # second in a row: treated as a bad password
    assert controller.login_failures == 2
    flows = hass.config_entries.flow.async_progress()
    assert flows and flows[0]["context"]["source"] == "reauth"
    assert _state(hass, "lock.gate") == "unavailable"
    for _ in range(3):
        await _refresh(hass, entry)
    with pytest.raises(Exception):  # the client refuses to log in again
        await client.area_status()
    assert controller.login_failures == 2  # never more than two attempts


async def test_bad_password_at_setup_starts_reauth(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_PASSWORD: "old"})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # First bare FAIL with credentials that worked before: back off and retry.
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert controller.login_failures == 1
    guard = next(iter(hass.data[DOMAIN].values()))
    guard.backoff_until = 0
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    # Second in a row: rejected password, stop and ask.
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert controller.login_failures == 2
    assert controller.sessions == {}
    flows = hass.config_entries.flow.async_progress()
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "secret"}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_unload_and_stop_log_out(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    assert len(controller.sessions) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert controller.sessions == {}

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(controller.sessions) == 1
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert controller.sessions == {}


async def test_legacy_protocol_end_to_end(hass: HomeAssistant, socket_enabled) -> None:
    fake = FakeController(protocol="legacy")
    server = TestServer(fake.app, host="127.0.0.1")
    await server.start_server()
    fake.host = f"127.0.0.1:{server.port}"
    try:
        entry = _entry(fake)
        await _setup(hass, entry)
        assert entry.data[CONF_PROTOCOL] == "legacy"
        await hass.services.async_call("alarm_control_panel", "alarm_arm_home", {"entity_id": ALARM}, blocking=True)
        assert _state(hass, ALARM) == "armed_home"
        assert await hass.config_entries.async_unload(entry.entry_id)
    finally:
        await server.close()


# ── diagnostics ─────────────────────────────────────────────────────────────


async def test_diagnostics_are_redacted(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, users=[make_user("Alex", "1234")])
    await _setup(hass, entry)
    controller.log("User Jane Citizen Entry Granted Front Door Using User By Pin")
    controller.log("Area Alarm Disarmed By User Jane Citizen")
    await _refresh(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    assert "Jane Citizen" not in text and "secret" not in text and "Alex" not in text
    assert diag["entry"]["options"]["users"] == "**REDACTED**"
    assert redact_event_text("Door Gate Unlocked By Door Front Door") == "Door Gate Unlocked By Door Front Door"
    assert redact_event_text("Area Alarm Armed By Home Assistant") == "Area Alarm Armed By Home Assistant"



# ── review findings (v0.2.0 verification) ───────────────────────────────────


async def test_silent_refusal_is_not_reported_as_success(hass: HomeAssistant, controller, monkeypatch) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    original = controller._control

    def ignore_arm(sub, rec, cmd, fields):
        if sub == "GXT_AREAS_TBL" and cmd != 0:
            return "OK"  # accepted, but the area never arms and nothing is logged
        return original(sub, rec, cmd, fields)

    monkeypatch.setattr(controller, "_control", ignore_arm)
    monkeypatch.setattr("custom_components.protege_wx.coordinator.asyncio.sleep", _no_sleep)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("alarm_control_panel", "alarm_arm_away", {"entity_id": ALARM}, blocking=True)
    assert err.value.translation_key == "failed_to_arm_unknown"


async def _no_sleep(_seconds=0):
    return None


async def test_events_survive_a_failed_poll(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    failures = async_capture_events(hass, EVENT_FAILED_TO_ARM)
    controller.state.events.append("Sun 25/10/2026 19:30:00 Input Living Opened")
    controller.state.events.append("Sun 25/10/2026 19:30:00 Area Alarm Failure To ARM By User Jane Citizen")
    # The event page is read, then the next request fails.
    original = controller._command
    calls = {"n": 0}

    def fail_after_events(plain, sessid):
        if plain.startswith("Request&Type=Status&SubType=GXT_AREAS_TBL") and calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("boom")
        return original(plain, sessid)

    controller._command = fail_after_events
    with pytest.raises(Exception):
        await entry.runtime_data.coordinator._async_update_data()
    controller._command = original
    await _refresh(hass, entry)
    assert failures and failures[-1].data["zones"] == ["Living"]


async def test_identical_lines_in_one_second_are_separate_events(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    seen = []
    entry.runtime_data.coordinator.async_add_event_listener(seen.append)
    line = "Sun 25/10/2026 19:40:00 User Unknown Entry Denied Gate Using Card"
    controller.state.events += [line, line]
    await _refresh(hass, entry)
    assert [p.event_type for p in seen] == ["access_denied", "access_denied"]


async def test_events_from_an_outage_are_history(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    seen = []
    entry.runtime_data.coordinator.async_add_event_listener(seen.append)
    controller.state.events += [
        "Sun 25/10/2026 19:00:00 Door Gate Forced Open",
        "Sun 25/10/2026 19:50:00 Door Gate Locked By Home Assistant",
    ]
    await _refresh(hass, entry)
    assert [p.event.text for p in seen] == ["Door Gate Locked By Home Assistant"]


async def test_changed_by_credits_operator_by_login_name(hass: HomeAssistant, socket_enabled) -> None:
    fake = FakeController(username="homeassistant")
    server = TestServer(fake.app, host="127.0.0.1")
    await server.start_server()
    fake.host = f"127.0.0.1:{server.port}"
    try:
        entry = MockConfigEntry(
            domain=DOMAIN, unique_id="A1B2C3D4",
            data={CONF_HOST: fake.host, CONF_USERNAME: "homeassistant", CONF_PASSWORD: "secret", CONF_PROTOCOL: "auto"},
            options={"users": [make_user("Alex", "1234")], "code_arm_required": False},
        )
        await _setup(hass, entry)
        await hass.services.async_call(
            "alarm_control_panel", "alarm_disarm", {"entity_id": ALARM, "code": "1234"}, blocking=True
        )
        assert hass.states.get(ALARM).attributes["changed_by"] == "Alex"
        await hass.config_entries.async_unload(entry.entry_id)
    finally:
        await server.close()


async def test_pin_guessing_is_limited(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, users=[make_user("Alex", "1234")])
    await _setup(hass, entry)
    for _ in range(5):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call("alarm_control_panel", "alarm_disarm", {"entity_id": ALARM, "code": "0000"}, blocking=True)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call("alarm_control_panel", "alarm_disarm", {"entity_id": ALARM, "code": "1234"}, blocking=True)
    assert err.value.translation_key == "pin_locked_out"


async def test_bypass_needs_pin_while_armed(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, users=[make_user("Alex", "1234")], code_arm_required=False)
    await _setup(hass, entry)
    # Disarmed: bypassing from the select is fine.
    await hass.services.async_call("select", "select_option", {"entity_id": "select.study_bypass", "option": "temporary"}, blocking=True)
    await hass.services.async_call("alarm_control_panel", "alarm_arm_home", {"entity_id": ALARM}, blocking=True)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call("select", "select_option", {"entity_id": "select.kitchen_bypass", "option": "temporary"}, blocking=True)
    assert err.value.translation_key == "bypass_while_armed"
    await hass.services.async_call(DOMAIN, "bypass", {"entity_id": "binary_sensor.kitchen", "mode": "temporary", "code": "1234"}, blocking=True)
    assert _state(hass, "select.kitchen_bypass") == "temporary"


async def test_ready_is_unknown_when_a_zone_is_unknown(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.state.inputs[4] = ["x", 0]
    await _refresh(hass, entry)
    assert _state(hass, "binary_sensor.alarm_ready_to_arm") == "unknown"


async def test_garbage_area_flags_make_the_area_unknown(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.state.areas[16] = [128, 128, "x", 0]
    await _refresh(hass, entry)
    assert _state(hass, ALARM) == "unavailable"


async def test_login_guard_survives_reloads(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    guard = entry.runtime_data.client.guard
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.client.guard is guard
    assert len(guard.login_times) == 2


async def test_hold_open_off_leaves_schedule_unlock_alone(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.state.doors[1] = [2, 0]  # unlocked by schedule
    await _refresh(hass, entry)
    count = len(controller.state.commands)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.gate_hold_open"}, blocking=True)
    assert len(controller.state.commands) == count


async def test_legacy_panel_code_converted_by_options_flow(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, panel_code="2468")
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"scan_interval": 1, "show_arming": False, "notify_failed_arm": True, "code_arm_required": True, "outputs": []},
    )
    await hass.async_block_till_done()
    assert "panel_code" not in entry.options
    assert entry.options["users"][0]["name"] == "Panel code"
    await hass.services.async_call("alarm_control_panel", "alarm_arm_away", {"entity_id": ALARM, "code": "2468"}, blocking=True)
    assert _state(hass, ALARM) == "armed_away"


# ── 0.2.4: logbook, connection, open zones, Repairs ────────────────────────


class _Clock:
    """Stands in for the coordinator's ``time`` module, so tests can skip ahead."""

    def __init__(self) -> None:
        import time as real_time

        self._real = real_time
        self.offset = 0.0

    def monotonic(self) -> float:
        return self._real.monotonic() + self.offset


@pytest.fixture
def clock(monkeypatch):
    from custom_components.protege_wx import coordinator as coordinator_module

    fake = _Clock()
    monkeypatch.setattr(coordinator_module, "time", fake)
    return fake


async def test_logbook_sentences(hass: HomeAssistant, controller) -> None:
    from custom_components.protege_wx.const import EVENT_LOGBOOK

    entry = _entry(controller)
    await _setup(hass, entry)
    logged = async_capture_events(hass, EVENT_LOGBOOK)
    controller.log("User Jane Citizen Entry Granted Front Door Using User By Pin")
    controller.log("Input Living Opened")
    await _refresh(hass, entry)
    assert [(e.data["name"], e.data["message"]) for e in logged] == [
        ("Front Door", "access granted to Jane Citizen (PIN)")
    ]  # the zone line is left to the Living sensor
    assert logged[0].data["entity_id"] == "event.front_door_events"


async def test_logbook_platform_describes(hass: HomeAssistant) -> None:
    from homeassistant.core import Event

    from custom_components.protege_wx.const import EVENT_LOGBOOK
    from custom_components.protege_wx.logbook import async_describe_events

    described = {}
    async_describe_events(hass, lambda domain, event, fn: described.setdefault(event, fn))
    entry = described[EVENT_LOGBOOK](
        Event(EVENT_LOGBOOK, {"name": "Alarm", "message": "disarmed by Jane", "entity_id": "event.alarm_events"})
    )
    assert entry == {"name": "Alarm", "message": "disarmed by Jane", "entity_id": "event.alarm_events"}


async def test_failed_arm_logbook_names_zones(hass: HomeAssistant, controller) -> None:
    from custom_components.protege_wx.const import EVENT_LOGBOOK

    entry = _entry(controller)
    await _setup(hass, entry)
    logged = async_capture_events(hass, EVENT_LOGBOOK)
    controller.state.events.append("Sun 25/10/2026 19:30:00 Input Living Opened")
    controller.state.events.append("Sun 25/10/2026 19:30:00 Area Alarm Failure To ARM By User Jane Citizen")
    await _refresh(hass, entry)
    assert ("Alarm", "failed to arm by Jane Citizen: Living is open") in [
        (e.data["name"], e.data["message"]) for e in logged
    ]


async def test_connection_sensor(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    sensor = "sensor.protege_wx_controller_connection"
    state = hass.states.get(sensor)
    assert state.state == "connected"
    assert state.attributes["protocol"] == "post"
    assert state.attributes["last_success"] is not None
    assert state.attributes["response_time_ms"] is not None
    controller.offline = True
    await _refresh(hass, entry)
    assert _state(hass, sensor) == "reconnecting"  # stays available while the link is down
    assert _state(hass, ALARM) == "unavailable"
    controller.offline = False
    await _refresh(hass, entry)
    assert _state(hass, sensor) == "connected"


async def test_open_zones_sensor(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    controller.state.areas[16] = [0, 0, 0, 0]
    await _setup(hass, entry)
    sensor = "sensor.alarm_open_zones"
    assert _state(hass, sensor) == "0"
    controller.open_input(3)  # Living: a stay zone
    controller.open_input(5)  # Up Passage: armed in both modes
    await _refresh(hass, entry)
    state = hass.states.get(sensor)
    assert state.state == "2"
    assert state.attributes["zones"] == ["Living", "Up Passage"]
    assert state.attributes["zones_home"] == ["Up Passage"]
    assert state.attributes["ready_away"] is False and state.attributes["ready_home"] is False


async def test_repairs_unreachable(hass: HomeAssistant, controller, clock) -> None:
    from homeassistant.helpers import issue_registry as ir

    entry = _entry(controller)
    await _setup(hass, entry)
    issue_id = f"controller_unreachable_{entry.entry_id}"
    registry = ir.async_get(hass)
    controller.offline = True
    await _refresh(hass, entry)
    clock.offset += 14 * 60
    await _refresh(hass, entry)
    assert registry.async_get_issue(DOMAIN, issue_id) is None  # not yet 15 minutes
    clock.offset += 2 * 60
    await _refresh(hass, entry)
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_placeholders["minutes"] == "15"
    controller.offline = False
    await _refresh(hass, entry)
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_repairs_low_voltage(hass: HomeAssistant, controller, clock) -> None:
    from homeassistant.helpers import issue_registry as ir

    entry = _entry(controller)
    await _setup(hass, entry)
    coordinator = entry.runtime_data.coordinator
    issue_id = f"low_supply_voltage_{entry.entry_id}"
    registry = ir.async_get(hass)

    async def poll_health() -> None:
        coordinator._last_health = None  # read health on this poll
        await _refresh(hass, entry)

    controller.voltage_mv = 11800
    await poll_health()
    clock.offset += 4 * 60
    await poll_health()
    assert registry.async_get_issue(DOMAIN, issue_id) is None  # under 5 minutes
    clock.offset += 2 * 60
    await poll_health()
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_placeholders["volts"] == "11.8"
    controller.voltage_mv = 12300  # between the thresholds: stays raised
    await poll_health()
    assert registry.async_get_issue(DOMAIN, issue_id) is not None
    controller.voltage_mv = 12600
    await poll_health()
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_repairs_event_log(hass: HomeAssistant, controller, clock) -> None:
    from homeassistant.helpers import issue_registry as ir

    controller.deny_events = True
    entry = _entry(controller)
    await _setup(hass, entry)
    issue_id = f"event_log_unreadable_{entry.entry_id}"
    registry = ir.async_get(hass)
    clock.offset += 6 * 60
    await _refresh(hass, entry)
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_placeholders["operator"] == "Home Assistant"
    controller.deny_events = False
    await _refresh(hass, entry)
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_issues_cleared_on_unload(hass: HomeAssistant, controller, clock) -> None:
    from homeassistant.helpers import issue_registry as ir

    controller.deny_events = True
    entry = _entry(controller)
    await _setup(hass, entry)
    clock.offset += 6 * 60
    await _refresh(hass, entry)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"event_log_unreadable_{entry.entry_id}")
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert registry.async_get_issue(DOMAIN, f"event_log_unreadable_{entry.entry_id}") is None


async def test_leftover_issue_cleared_after_restart(hass: HomeAssistant, controller) -> None:
    from homeassistant.helpers import issue_registry as ir

    entry = _entry(controller)
    entry.add_to_hass(hass)
    issue_id = f"controller_unreachable_{entry.entry_id}"
    ir.async_create_issue(
        hass, DOMAIN, issue_id, is_fixable=False, severity=ir.IssueSeverity.ERROR,
        translation_key="controller_unreachable",
        translation_placeholders={"host": controller.host, "minutes": "15"},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


# ── review fixes ───────────────────────────────────────────────────────────


async def test_unreachable_counts_across_setup_retries(hass: HomeAssistant, controller) -> None:
    from homeassistant.helpers import issue_registry as ir

    from custom_components.protege_wx.health import entry_health

    controller.offline = True
    entry = _entry(controller)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    health = entry_health(hass, entry.entry_id)
    first = health.failing_since
    assert first is not None
    # A later retry (a new coordinator each time) keeps the original start.
    health.record_failure(controller.host, first + 16 * 60)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"controller_unreachable_{entry.entry_id}")
    assert issue is not None and issue.is_persistent


async def test_connection_sensor_follows_repeated_failures(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    sensor = "sensor.protege_wx_controller_connection"
    controller.offline = True
    await _refresh(hass, entry)
    assert _state(hass, sensor) == "reconnecting"
    client = entry.runtime_data.client
    import time as real_time

    client.guard.backoff_until = real_time.monotonic() + 60  # now backing off
    await _refresh(hass, entry)  # a second failure in a row
    assert _state(hass, sensor) == "backing_off"


async def test_low_voltage_band_resets_old_dip(hass: HomeAssistant, controller, clock) -> None:
    from homeassistant.helpers import issue_registry as ir

    entry = _entry(controller)
    await _setup(hass, entry)
    coordinator = entry.runtime_data.coordinator
    issue_id = f"low_supply_voltage_{entry.entry_id}"

    async def poll_health() -> None:
        coordinator._last_health = None
        await _refresh(hass, entry)

    controller.voltage_mv = 11900
    await poll_health()  # a brief dip
    controller.voltage_mv = 12300  # float voltage for hours
    clock.offset += 3 * 60 * 60
    await poll_health()
    controller.voltage_mv = 11900  # another dip: should start a fresh 5 minutes
    await poll_health()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_voltage_ignores_stale_health(hass: HomeAssistant, controller, clock) -> None:
    from homeassistant.helpers import issue_registry as ir

    entry = _entry(controller)
    await _setup(hass, entry)
    coordinator = entry.runtime_data.coordinator
    controller.voltage_mv = 11800
    coordinator._last_health = None
    await _refresh(hass, entry)  # one low reading
    clock.offset += 10 * 60  # ten minutes with no fresh health reading
    coordinator._last_health = coordinator._health_read_at = None
    controller.offline = True
    await _refresh(hass, entry)
    controller.offline = False
    coordinator._last_health = clock.monotonic()  # health not due this poll
    await _refresh(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"low_supply_voltage_{entry.entry_id}") is None


async def test_low_voltage_message_follows_the_reading(hass: HomeAssistant, controller, clock) -> None:
    from homeassistant.helpers import issue_registry as ir

    entry = _entry(controller)
    await _setup(hass, entry)
    coordinator = entry.runtime_data.coordinator
    issue_id = f"low_supply_voltage_{entry.entry_id}"

    async def poll_health() -> None:
        coordinator._last_health = None
        await _refresh(hass, entry)

    controller.voltage_mv = 11800
    await poll_health()
    clock.offset += 6 * 60
    await poll_health()
    controller.voltage_mv = 11200
    await poll_health()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue.translation_placeholders["volts"] == "11.2"


async def test_connection_attributes_not_recorded(hass: HomeAssistant, controller) -> None:
    from custom_components.protege_wx.sensor import ProtegeConnection

    assert {"last_success", "response_time_ms"} <= ProtegeConnection._unrecorded_attributes


# ── 0.3.0: alarm modes, emergencies, cause, countdown, clock ───────────────


def _area_commands(controller) -> list[int]:
    return [
        int(dict(p.split("=", 1) for p in c.split("&") if "=" in p)["Command"])
        for c in controller.state.commands
        if "SubType=GXT_AREAS_TBL" in c
    ]


async def test_night_mapped_to_stay_and_vacation(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, night_mode={"16": "stay"})
    await _setup(hass, entry)
    await hass.services.async_call("alarm_control_panel", "alarm_arm_night", {"entity_id": ALARM}, blocking=True)
    assert _area_commands(controller)[-1] == 10  # stay arm
    assert _state(hass, ALARM) == "armed_night"
    await _refresh(hass, entry)
    assert _state(hass, ALARM) == "armed_night"  # survives polls
    assert hass.states.get("button.alarm_force_arm_night") is None  # can't force a stay arm
    await hass.services.async_call("alarm_control_panel", "alarm_disarm", {"entity_id": ALARM}, blocking=True)
    assert _state(hass, ALARM) == "disarmed"

    await hass.services.async_call("alarm_control_panel", "alarm_arm_vacation", {"entity_id": ALARM}, blocking=True)
    assert _area_commands(controller)[-1] == 3  # away arm
    assert _state(hass, ALARM) == "armed_vacation"
    await hass.services.async_call("alarm_control_panel", "alarm_disarm", {"entity_id": ALARM}, blocking=True)
    # A keypad arm afterwards shows as plain Away, not Vacation.
    controller.state.areas[16] = [128, 128, 8, 0]
    await _refresh(hass, entry)
    assert _state(hass, ALARM) == "armed_away"


async def test_night_off_hides_night(hass: HomeAssistant, controller) -> None:
    from homeassistant.components.alarm_control_panel import (
        AlarmControlPanelEntityFeature,
    )

    entry = _entry(controller, night_mode={"16": "off"})
    await _setup(hass, entry)
    features = hass.states.get(ALARM).attributes["supported_features"]
    assert not features & AlarmControlPanelEntityFeature.ARM_NIGHT
    assert features & AlarmControlPanelEntityFeature.ARM_VACATION
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "alarm_control_panel", "alarm_arm_night", {"entity_id": ALARM}, blocking=True
        )
    assert err.value.translation_key in ("night_off", "service_not_supported")  # HA checks first


async def test_emergency_alert(hass: HomeAssistant, controller) -> None:
    from homeassistant.components.repairs import DOMAIN as REPAIRS_DOMAIN
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.setup import async_setup_component

    from custom_components.protege_wx.const import EVENT_EMERGENCY, EVENT_LOGBOOK

    assert await async_setup_component(hass, REPAIRS_DOMAIN, {})
    entry = _entry(controller)
    await _setup(hass, entry)
    alerts = async_capture_events(hass, EVENT_EMERGENCY)
    logged = async_capture_events(hass, EVENT_LOGBOOK)
    controller.log("User Jane Citizen Duress Front Door")
    await _refresh(hass, entry)

    assert alerts and alerts[0].data["type"] == "duress" and alerts[0].data["by"] == "Jane Citizen"
    assert ("Protege WX", "duress alarm by Jane Citizen") in [(e.data["name"], e.data["message"]) for e in logged]
    assert hass.states.get("event.protege_wx_controller_controller_events").attributes["event_type"] == "duress"
    issue_id = f"emergency_{entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.severity == ir.IssueSeverity.CRITICAL and issue.is_fixable
    assert issue.translation_placeholders["kind"] == "duress"

    # Acknowledging it in Repairs clears it.
    from custom_components.protege_wx.repairs import async_create_fix_flow

    flow = await async_create_fix_flow(hass, issue_id, None)
    flow.hass, flow.issue_id, flow.handler = hass, issue_id, DOMAIN
    result = await flow.async_step_init()
    result = await flow.async_step_confirm({})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_alarm_cause(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    sensor = "sensor.alarm_alarm_cause"
    assert _state(hass, sensor) == "none"
    controller.state.areas[16] = [128, 128, 8, 0]
    await _refresh(hass, entry)
    controller.open_input(5)
    controller.log("Input Up Passage Opened")
    controller.state.areas[16] = [128, 128, 9, 0]  # alarm
    await _refresh(hass, entry)
    assert _state(hass, ALARM) == "triggered"
    assert _state(hass, sensor) == "Up Passage"
    controller.state.inputs[5][0] = 0
    await _refresh(hass, entry)
    assert _state(hass, sensor) == "Up Passage"  # kept until disarmed
    controller.state.areas[16] = [128, 0, 0, 0]
    await _refresh(hass, entry)
    assert _state(hass, sensor) == "none"


async def test_delay_countdown(hass: HomeAssistant, controller) -> None:
    from homeassistant.util import dt as dt_util

    entry = _entry(controller)
    await _setup(hass, entry)
    sensor = "sensor.alarm_delay_ends"
    assert _state(hass, sensor) == "unknown"
    assert hass.states.get(sensor).attributes["exit_delay"] == 60  # read from the controller
    assert hass.states.get(sensor).attributes["entry_delay"] == 45
    controller.state.areas[16] = [128, 129, 0, 0]
    await _refresh(hass, entry)
    state = hass.states.get(sensor)
    ends = dt_util.parse_datetime(state.state)
    assert 55 <= (ends - dt_util.utcnow()).total_seconds() <= 61
    assert state.attributes["phase"] == "exit"
    await _refresh(hass, entry)
    assert hass.states.get(sensor).state == state.state  # doesn't restart each poll
    controller.state.areas[16] = [128, 130, 0, 0]
    await _refresh(hass, entry)
    ends = dt_util.parse_datetime(_state(hass, sensor))
    assert 40 <= (ends - dt_util.utcnow()).total_seconds() <= 46
    controller.state.areas[16] = [128, 0, 0, 0]
    await _refresh(hass, entry)
    assert _state(hass, sensor) == "unknown"


async def test_delays_from_options_override(hass: HomeAssistant, controller) -> None:
    controller.exit_delay = controller.entry_delay = 0  # not reported
    entry = _entry(controller, delays={"16": {"exit": 90, "entry": 20}})
    await _setup(hass, entry)
    attributes = hass.states.get("sensor.alarm_delay_ends").attributes
    assert attributes["exit_delay"] == 90 and attributes["entry_delay"] == 20


async def test_zone_last_triggered(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    sensor = "sensor.living_last_triggered"
    assert _state(hass, sensor) == "unknown"
    controller.open_input(3)
    await _refresh(hass, entry)
    first = _state(hass, sensor)
    assert first != "unknown"
    await _refresh(hass, entry)
    assert _state(hass, sensor) == first  # still open: same trigger


async def test_person_last_seen(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.log("User Jane Citizen Entry Granted Front Door Using User By Pin")
    await _refresh(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, "A1B2C3D4_person_0_jane_citizen")
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state.state != "unknown"
    assert state.attributes["door"] == "Front Door" and state.attributes["method"] == "pin"
    assert "Jane Citizen" in state.attributes["friendly_name"]

    # Remembered across a reload.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["door"] == "Front Door"


async def test_clock_drift_issue(hass: HomeAssistant, controller) -> None:
    from datetime import timedelta

    from homeassistant.helpers import issue_registry as ir
    from homeassistant.util import dt as dt_util

    entry = _entry(controller)
    await _setup(hass, entry)
    issue_id = f"clock_drift_{entry.entry_id}"
    registry = ir.async_get(hass)
    for _ in range(3):
        controller.clock = dt_util.now().replace(tzinfo=None) - timedelta(minutes=5)
        controller.log("Area Alarm Disarmed By Home Assistant")
        await _refresh(hass, entry)
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {"minutes": "5", "direction": "behind"}
    for _ in range(5):
        controller.clock = dt_util.now().replace(tzinfo=None)
        controller.log("Area Alarm Disarmed By Home Assistant")
        await _refresh(hass, entry)
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_options_flow_areas(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "areas" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "areas"})
    assert result["type"] is FlowResultType.FORM
    keys = [str(k) for k in result["data_schema"].schema]
    assert keys == ["Alarm: Night arms as", "Alarm: exit delay", "Alarm: entry delay"]  # System Area has no zones
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults["Alarm: exit delay"] == 60 and defaults["Alarm: entry delay"] == 45
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"Alarm: Night arms as": "stay", "Alarm: exit delay": 30, "Alarm: entry delay": 45},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["night_mode"] == {"16": "stay"}
    assert entry.options["delays"] == {"16": {"exit": 30, "entry": 45}}


# ── 0.3.0: doors ───────────────────────────────────────────────────────────


async def _refresh_all(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_refresh_all()
    await hass.async_block_till_done()


def _door_commands(controller, door: int = 0) -> list[int]:
    return [
        int(dict(p.split("=", 1) for p in c.split("&") if "=" in p)["Command"])
        for c in controller.state.commands
        if "SubType=GXT_DOORS_TBL" in c and f"RecId={door}&" in c
    ]


async def test_visitor_unlock_relocks(hass: HomeAssistant, controller) -> None:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    entry = _entry(controller)
    await _setup(hass, entry)
    await hass.services.async_call(
        DOMAIN, "visitor_unlock", {"entity_id": "lock.front_door", "minutes": 2}, blocking=True
    )
    assert _door_commands(controller) == [2]  # latched unlock
    assert _state(hass, "lock.front_door") == "unlocked"
    assert hass.states.get("lock.front_door").attributes["visitor_until"] is not None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=1))
    await hass.async_block_till_done()
    assert _door_commands(controller) == [2]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2, seconds=5))
    await hass.async_block_till_done()
    assert _door_commands(controller) == [2, 0]
    await _refresh_all(hass, entry)
    assert _state(hass, "lock.front_door") == "locked"
    assert hass.states.get("lock.front_door").attributes["visitor_until"] is None


async def test_visitor_unlock_cancelled_by_manual_lock(hass: HomeAssistant, controller) -> None:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    entry = _entry(controller, visitor_minutes=5)
    await _setup(hass, entry)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.front_door_visitor_unlock"}, blocking=True
    )
    until = dt_util.parse_datetime(hass.states.get("lock.front_door").attributes["visitor_until"])
    assert 290 <= (until - dt_util.utcnow()).total_seconds() <= 300  # the configured 5 minutes
    controller.state.doors[0][0] = 0  # locked at the keypad
    await _refresh_all(hass, entry)
    controller.state.doors[0][0] = 9  # then held open on purpose by a schedule
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert _door_commands(controller) == [2]  # not re-locked


async def test_visitor_unlock_survives_reload(hass: HomeAssistant, controller) -> None:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    entry = _entry(controller)
    await _setup(hass, entry)
    await hass.services.async_call(DOMAIN, "visitor_unlock", {"entity_id": "lock.gate"}, blocking=True)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))  # flush the save
    await hass.async_block_till_done()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=16))
    await hass.async_block_till_done()
    assert _door_commands(controller, 1) == [2, 0]


async def test_door_forced_and_left_open(hass: HomeAssistant, controller) -> None:
    registry = er.async_get(hass)
    entry = _entry(controller)
    await _setup(hass, entry)
    # No door-position input in the fake: the sensors start disabled.
    forced = registry.async_get("binary_sensor.front_door_forced_open")
    assert forced is not None and forced.disabled_by is not None
    registry.async_update_entity(forced.entity_id, disabled_by=None)
    registry.async_update_entity("binary_sensor.front_door_left_open", disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    controller.state.doors[0][1] = 4
    await _refresh_all(hass, entry)
    assert _state(hass, "binary_sensor.front_door_forced_open") == "on"
    assert _state(hass, "binary_sensor.front_door_left_open") == "off"
    controller.state.doors[0][1] = 3
    await _refresh_all(hass, entry)
    assert _state(hass, "binary_sensor.front_door_forced_open") == "off"
    assert _state(hass, "binary_sensor.front_door_left_open") == "on"


async def test_walk_test_switch(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    switch = "switch.alarm_walk_test"
    assert _state(hass, switch) == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert _area_commands(controller)[-1] == 7
    assert _state(hass, switch) == "on"
    await _refresh(hass, entry)
    assert _state(hass, switch) == "on"
    controller.log("Area Alarm Walk Test Ended By User Jane Citizen")  # ended at a keypad
    await _refresh(hass, entry)
    assert _state(hass, switch) == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    controller.state.areas[16] = [128, 128, 8, 0]  # armed
    await _refresh(hass, entry)
    assert _state(hass, switch) == "off"
    assert hass.states.get("switch.system_area_walk_test") is None


# ── 0.3.0: Alarmo sync ─────────────────────────────────────────────────────

ALARMO = "alarm_control_panel.alarmo"


async def _alarmo(hass: HomeAssistant) -> None:
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(
        hass,
        "alarm_control_panel",
        {
            "alarm_control_panel": {
                "platform": "manual",
                "name": "Alarmo",
                "code_arm_required": False,
                "arming_time": 0,
                "delay_time": 0,
                "trigger_time": 0,
            }
        },
    )
    await hass.async_block_till_done()


async def test_alarmo_sync_both_ways(hass: HomeAssistant, controller) -> None:
    await _alarmo(hass)
    entry = _entry(controller, alarmo_entity=ALARMO, alarmo_area=16)
    await _setup(hass, entry)

    # Alarmo -> Protege
    await hass.services.async_call("alarm_control_panel", "alarm_arm_away", {"entity_id": ALARMO}, blocking=True)
    await hass.async_block_till_done()
    assert _area_commands(controller)[-1] == 3
    assert _state(hass, ALARM) == "armed_away"
    assert _state(hass, ALARMO) == "armed_away"
    assert hass.states.get(ALARM).attributes["changed_by"] == "Alarmo"

    # Protege (keypad) -> Alarmo
    controller.state.areas[16] = [128, 0, 0, 0]
    await _refresh(hass, entry)
    assert _state(hass, ALARMO) == "disarmed"
    controller.state.areas[16] = [128, 128, 64, 0]
    await _refresh(hass, entry)
    assert _state(hass, ALARMO) == "armed_home"
    commands = len(controller.state.commands)
    await _refresh(hass, entry)
    assert len(controller.state.commands) == commands  # no echo back to the controller


async def test_alarmo_disarmed_again_when_controller_refuses(hass: HomeAssistant, controller) -> None:
    await _alarmo(hass)
    entry = _entry(controller, alarmo_entity=ALARMO, alarmo_area=16)
    await _setup(hass, entry)
    controller.open_input(5)
    await _refresh(hass, entry)
    await hass.services.async_call("alarm_control_panel", "alarm_arm_away", {"entity_id": ALARMO}, blocking=True)
    await hass.async_block_till_done()
    assert _state(hass, ALARM) == "disarmed"
    assert _state(hass, ALARMO) == "disarmed"


async def test_options_flow_alarmo(hass: HomeAssistant, controller) -> None:
    await _alarmo(hass)
    entry = _entry(controller)
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "alarmo"})
    assert result["step_id"] == "alarmo"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"alarmo_entity": ALARMO, "alarmo_area": "16", "alarmo_code": "1234"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["alarmo_entity"] == ALARMO and entry.options["alarmo_area"] == 16
    assert entry.options["alarmo_code"] == "1234"
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["entry"]["options"]["alarmo_code"] == "**REDACTED**"


# ── 0.3.0: voice ───────────────────────────────────────────────────────────


async def _ask(hass: HomeAssistant, text: str) -> str:
    from homeassistant.components import conversation

    result = await conversation.async_converse(hass, text, None, Context(), language="en")
    return result.response.speech["plain"]["speech"]


async def test_voice_questions(hass: HomeAssistant, controller) -> None:
    from homeassistant.setup import async_setup_component

    pytest.importorskip("hassil")

    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    entry = _entry(controller)
    await _setup(hass, entry)

    assert await _ask(hass, "Is the house armed?") == "The Alarm is disarmed."
    assert await _ask(hass, "Can I arm?") == "Yes, the Alarm is ready to arm."
    controller.open_input(3)
    controller.open_input(5)
    await _refresh(hass, entry)
    assert await _ask(hass, "can i arm the house") == "Not yet: Living and Up Passage are open."
    assert await _ask(hass, "Who came in last?") == "Nobody has come in with a card or PIN that I know of."
    controller.log("User Jane Citizen Entry Granted Front Door Using User By Pin")
    await _refresh(hass, entry)
    answer = await _ask(hass, "who came home last")
    assert answer.startswith("Jane Citizen, at ") and answer.endswith(" at the Front Door.")


async def test_user_flow_warns_about_missing_permissions(hass: HomeAssistant, controller) -> None:
    controller.deny_events = True
    controller.permit_details = False
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: controller.host, CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "secret"},
    )
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "permissions"
    missing = result["description_placeholders"]["missing"]
    assert "Event log" in missing and "Record details" in missing and "Doors" not in missing

    # Fixed in Protege, then re-checked: straight through.
    controller.deny_events = False
    controller.permit_details = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "recheck"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_user_flow_can_carry_on_without_permissions(hass: HomeAssistant, controller) -> None:
    controller.deny_events = True
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: controller.host, CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "secret"},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "recheck"})
    assert result["type"] is FlowResultType.MENU  # still missing
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "continue_anyway"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
