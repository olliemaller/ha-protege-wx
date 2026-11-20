"""Edge cases the scenario tests don't reach: voice answers, flows, setup and controls."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.protege_wx import voice
from custom_components.protege_wx.const import DOMAIN

from .test_integration import (  # noqa: F401 - fixtures
    ALARM,
    _entry,
    _refresh,
    _setup,
    _state,
    controller,
    fast_retries,
)

# ── voice ──────────────────────────────────────────────────────────────────


async def test_voice_answers_without_an_alarm(hass: HomeAssistant) -> None:
    assert voice.answer_armed(hass) == "There's no alarm set up."
    assert voice.answer_ready(hass) == "There's no alarm set up."
    assert voice.answer_last_in(hass) == "Nobody has come in with a card or PIN that I know of."


async def test_voice_answers_follow_the_alarm(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)

    hass.states.async_set(ALARM, "unavailable")
    assert voice.answer_armed(hass) == "I can't reach the Alarm right now."

    controller.state.areas[16] = [128, 129, 0, 0]  # armed away
    await _refresh(hass, entry)
    assert voice.answer_armed(hass) == "The Alarm is armed away."
    assert voice.answer_ready(hass) == "The Alarm is already armed."

    controller.state.areas[16] = [128, 0, 0, 0]
    controller.state.inputs[4] = ["x", 0]  # a zone the controller can't report
    await _refresh(hass, entry)
    assert voice.answer_ready(hass) == "I can't tell if the Alarm is ready right now."

    controller.state.inputs[4] = [0, 0]
    controller.open_input(3)  # Living, a stay zone: home mode still works
    await _refresh(hass, entry)
    assert voice.answer_ready(hass) == (
        "Not yet: Living is open, but you can arm it in home mode."
    )


def test_voice_says_when(hass: HomeAssistant) -> None:
    now = dt_util.now().replace(hour=15, minute=4)
    with patch.object(voice.dt_util, "now", return_value=now):
        assert voice._when(now) == "at 3:04 pm"
        assert voice._when(now - timedelta(days=1)) == "yesterday at 3:04 pm"
        older = now - timedelta(days=9)
        assert voice._when(older) == (
            f"on {older.strftime('%A %d %B').replace(' 0', ' ')} at 3:04 pm"
        )


async def test_voice_register_falls_back(hass: HomeAssistant) -> None:
    import builtins

    pytest.importorskip("homeassistant.components.conversation.agent_manager")

    real_import = builtins.__import__
    handler = AsyncMock()

    def _no(*names: str):
        def _import(name, *args, **kwargs):
            if name in names:
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        return _import

    # Home Assistant 2025.6 and older: the default agent registers sentences itself.
    agent = MagicMock()
    hass.data["conversation_default_entity"] = agent
    with (
        patch(
            "builtins.__import__",
            _no("homeassistant.components.conversation.agent_manager"),
        ),
        patch(
            "homeassistant.components.conversation.const.DATA_DEFAULT_ENTITY",
            "conversation_default_entity",
            create=True,
        ),
    ):
        assert voice._register(hass, ["hi"], handler) is agent.register_trigger.return_value
    agent.register_trigger.assert_called_once_with(["hi"], handler)

    # 2026: no TriggerDetails, sentences go straight to the agent manager.
    manager = MagicMock()
    with (
        patch(
            "homeassistant.components.conversation.agent_manager.get_agent_manager",
            return_value=manager,
        ),
        patch("builtins.__import__", _no("homeassistant.components.conversation.trigger")),
    ):
        assert voice._register(hass, ["hi"], handler) is manager.register_trigger.return_value
    manager.register_trigger.assert_called_once_with(["hi"], handler)

    # 2025.7 to 2025.12: sentences wrapped in TriggerDetails.
    manager = MagicMock()
    details = MagicMock()
    with (
        patch(
            "homeassistant.components.conversation.agent_manager.get_agent_manager",
            return_value=manager,
        ),
        patch(
            "homeassistant.components.conversation.trigger.TriggerDetails", details, create=True
        ),
    ):
        voice._register(hass, ["hi"], handler)
    details.assert_called_once_with(["hi"], handler)
    manager.register_trigger.assert_called_once_with(details.return_value)

    # Nothing to register with at all.
    hass.data.pop("conversation_default_entity", None)
    with patch(
        "builtins.__import__",
        _no(
            "homeassistant.components.conversation.agent_manager",
            "homeassistant.components.conversation.const",
        ),
    ):
        assert voice._register(hass, ["hi"], handler) is None


async def test_voice_registration_failure_is_quiet(hass: HomeAssistant) -> None:
    hass.config.components.add("conversation")
    with patch.object(voice, "_register", side_effect=RuntimeError("no assist")):
        release = voice.async_setup_voice(hass)
    assert hass.data[DOMAIN]["voice"]["remove"] == []
    release()
    assert "voice" not in hass.data[DOMAIN]



# ── config and options flows ────────────────────────────────────────────────

from aioprotegewx import ProtegeAuthError, ProtegeConnectionError, ProtegeError  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402

from custom_components.protege_wx import config_flow  # noqa: E402
from custom_components.protege_wx.users import make_user  # noqa: E402

LOGIN = {CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "secret"}


async def _menu(hass: HomeAssistant, entry, *steps: str):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    for step in steps:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": step}
        )
    return result


def test_unexpected_errors_are_unknown() -> None:
    assert config_flow._errors_for(RuntimeError("boom"), {}) == {"base": "unknown"}


async def test_permission_check_reads_errors_as_missing() -> None:
    client = MagicMock()
    client.list_records = AsyncMock(side_effect=ProtegeError("refused"))
    client.area_status = AsyncMock(return_value=[])
    client.input_status = AsyncMock(side_effect=ProtegeError("refused"))
    client.door_status = AsyncMock(return_value=[])
    client.get_record = AsyncMock(return_value={})
    client.events = AsyncMock(return_value=[])
    missing = await config_flow.check_permissions(client, {})
    assert missing == ["areas", "inputs", "events", "health"]

    client.list_records = AsyncMock(side_effect=ProtegeAuthError("logged out"))
    with pytest.raises(ProtegeAuthError):
        await config_flow.check_permissions(client, {})
    client.list_records = AsyncMock(return_value={1: "Alarm"})
    client.area_status = AsyncMock(side_effect=ProtegeAuthError("logged out"))
    with pytest.raises(ProtegeAuthError):
        await config_flow.check_permissions(client, {})


async def test_login_check_survives_missing_health(hass: HomeAssistant, controller) -> None:
    with patch(
        "aioprotegewx.ProtegeClient.health_values", AsyncMock(side_effect=ProtegeError("no"))
    ):
        extra = await config_flow.validate_login(hass, controller.host, **{
            "username": "Home Assistant", "password": "secret"
        })
    assert extra["serial"] is None
    assert "health" in extra["missing"]
    with (
        patch(
            "aioprotegewx.ProtegeClient.health_values",
            AsyncMock(side_effect=ProtegeAuthError("no")),
        ),
        pytest.raises(ProtegeAuthError),
    ):
        await config_flow.validate_login(hass, controller.host, "Home Assistant", "secret")


async def test_permission_recheck_failure_shows_the_warning_again(
    hass: HomeAssistant, controller
) -> None:
    from homeassistant import config_entries

    controller.deny_events = True
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: controller.host, **LOGIN}
    )
    assert result["step_id"] == "permissions"
    with patch.object(config_flow, "validate_login", AsyncMock(side_effect=OSError("gone"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "recheck"}
        )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "permissions"


async def test_reauth_and_reconfigure_errors(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    # Before the flow starts: older Home Assistant reloads on any entry change.
    hass.config_entries.async_update_entry(entry, unique_id="SOMETHING-ELSE")
    await hass.async_block_till_done()
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "Home Assistant", CONF_PASSWORD: "nope"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["reason"] == "wrong_controller"

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "https://192.0.2.5", **LOGIN}
    )
    assert result["errors"] == {"base": "https_not_supported"}


async def test_dhcp_move_reloads_a_loaded_entry(hass: HomeAssistant, controller) -> None:
    from homeassistant import config_entries
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

    entry = _entry(controller)
    await _setup(hass, entry)
    port = controller.host.rsplit(":", 1)[1]
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, config_flow.CONF_MAC: "00:1b:c2:aa:bb:cc"}
    )
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DhcpServiceInfo(ip="192.0.2.30", hostname="protege", macaddress="001bc2aabbcc"),
        )
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == f"192.0.2.30:{port}"
    from custom_components.protege_wx import _HAS_RELOADING_OPTIONS_FLOW

    if _HAS_RELOADING_OPTIONS_FLOW:  # older versions reload from the update listener
        reload.assert_called_once_with(entry.entry_id)


async def test_options_need_a_loaded_entry(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["reason"] == "not_loaded"


async def test_options_without_areas_or_inputs(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    site = entry.runtime_data.site
    with patch.object(site, "areas", {}), patch.object(site, "inputs", {}):
        for step in ("areas", "alarmo", "inputs"):
            result = await _menu(hass, entry, step)
            assert result["type"] is FlowResultType.ABORT, step
            assert result["reason"] in ("no_areas", "no_inputs")


async def test_options_alarmo_code_kept_and_cleared(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    hass.states.async_set("alarm_control_panel.alarmo", "disarmed")
    result = await _menu(hass, entry, "alarmo")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"alarmo_entity": "alarm_control_panel.alarmo", "alarmo_area": "16",
         "alarmo_direction": "both", "alarmo_code": " 4321 "},
    )
    await hass.async_block_till_done()
    assert entry.options["alarmo_code"] == "4321"
    result = await _menu(hass, entry, "alarmo")
    assert result["description_placeholders"] == {"code_set": "yes"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"alarmo_entity": "alarm_control_panel.alarmo", "alarmo_area": "16",
         "alarmo_direction": "both", "clear_code": True},
    )
    await hass.async_block_till_done()
    assert entry.options["alarmo_code"] is None


async def test_options_area_delays_back_to_default(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    area = next(a for a in entry.runtime_data.site.areas.values() if a.has_inputs is not False)
    key = config_flow._area_key
    result = await _menu(hass, entry, "areas")
    answers = {
        key(area, "night"): "off",
        key(area, "exit"): area.exit_delay + 5,
        key(area, "entry"): area.entry_delay,
    }
    await hass.config_entries.options.async_configure(result["flow_id"], answers)
    await hass.async_block_till_done()
    assert entry.options["delays"] == {str(area.id): {"exit": area.exit_delay + 5}}
    result = await _menu(hass, entry, "areas")
    answers[key(area, "exit")] = area.exit_delay
    await hass.config_entries.options.async_configure(result["flow_id"], answers)
    await hass.async_block_till_done()
    assert entry.options["delays"] == {}


async def test_options_edit_user(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    users = [
        await hass.async_add_executor_job(make_user, "Alex", "1234"),
        await hass.async_add_executor_job(make_user, "Sam", "5678"),
    ]
    entry = _entry(controller, users=users)
    await _setup(hass, entry)

    async def edit(**answers):
        result = await _menu(hass, entry, "users", "edit_user")
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"name": "Alex"}
        )
        assert result["step_id"] == "edit_user_details"
        return await hass.config_entries.options.async_configure(
            result["flow_id"], {"can_arm": True, "can_disarm": True, **answers}
        )

    assert (await edit(code="12ab", confirm_code="12ab"))["errors"] == {
        "code": "code_not_numeric"
    }
    assert (await edit(code="4444", confirm_code="4445"))["errors"] == {
        "confirm_code": "code_mismatch"
    }
    assert (await edit(code="5678", confirm_code="5678"))["errors"] == {"code": "code_in_use"}

    old_hash = entry.options["users"][0]
    result = await edit(code="4444", confirm_code="4444", can_arm=False)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    alex = entry.options["users"][0]
    assert alex["name"] == "Alex" and alex["can_arm"] is False
    assert alex != old_hash and "4444" not in str(alex)
    assert entry.options["users"][1] == users[1]

    # No new PIN: only the permissions and schedule change.
    result = await edit(can_disarm=False)
    await hass.async_block_till_done()
    assert entry.options["users"][0]["can_disarm"] is False
    assert entry.state is ConfigEntryState.LOADED


# ── setup, removal, card and shared entity code ─────────────────────────────

from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from homeassistant.helpers import device_registry as dr  # noqa: E402


async def test_unexpected_setup_error_still_logs_out(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.protege_wx.async_discover", AsyncMock(side_effect=RuntimeError("bug"))
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert controller.sessions == {}


async def test_only_gone_devices_can_be_removed(hass: HomeAssistant, controller) -> None:
    from custom_components.protege_wx import async_remove_config_entry_device

    entry = _entry(controller)
    await _setup(hass, entry)
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    assert devices
    for device in devices:
        assert not await async_remove_config_entry_device(hass, entry, device)
    gone = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "A1B2C3D4_door_99")}
    )
    assert await async_remove_config_entry_device(hass, entry, gone)


async def test_removing_the_entry_deletes_its_storage(hass: HomeAssistant, controller) -> None:
    from homeassistant.helpers import issue_registry as ir

    from custom_components.protege_wx.const import ISSUE_EMERGENCY

    entry = _entry(controller)
    await _setup(hass, entry)
    ir.async_create_issue(
        hass, DOMAIN, f"{ISSUE_EMERGENCY}_{entry.entry_id}", is_fixable=False,
        severity=ir.IssueSeverity.ERROR, translation_key="emergency",
    )
    hass.data[DOMAIN][("people", entry.entry_id)] = (0, {})
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ("people", entry.entry_id) not in hass.data.get(DOMAIN, {})
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_EMERGENCY}_{entry.entry_id}") is None


async def test_card_without_frontend_or_with_errors(hass: HomeAssistant, caplog) -> None:
    from custom_components.protege_wx import card

    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    await card.async_register_card(hass)
    hass.http.async_register_static_paths.assert_awaited_once()
    await card.async_register_card(hass)  # once per run
    hass.http.async_register_static_paths.assert_awaited_once()

    hass.data[DOMAIN].pop(card._KEY)
    hass.http.async_register_static_paths = AsyncMock(side_effect=RuntimeError("no http"))
    await card.async_register_card(hass)
    assert "Couldn't register the Protege alarm card" in caplog.text


def test_entity_id_change_hook_hands_on() -> None:
    from custom_components.protege_wx.entity import _entity_id_changed_hook

    seen: list[str] = []

    class Base:
        def async_entity_id_changed(self, old: str) -> None:
            seen.append(old)

    class Child(Base):
        pass

    Child.async_entity_id_changed = _entity_id_changed_hook(Child)  # type: ignore[method-assign]

    class Lonely:
        pass

    Lonely.async_entity_id_changed = _entity_id_changed_hook(Lonely)  # type: ignore[attr-defined]
    Child().async_entity_id_changed("lock.old")
    Lonely().async_entity_id_changed("lock.old")  # nothing above it: no error
    assert seen == ["lock.old"]


async def test_rejected_login_while_controlling(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    client = entry.runtime_data.client
    with (
        patch.object(client, "unlock_door", AsyncMock(side_effect=ProtegeAuthError("logged out"))),
        pytest.raises(HomeAssistantError) as err,
    ):
        await hass.services.async_call(
            "lock", "unlock", {"entity_id": "lock.front_door"}, blocking=True
        )
    assert err.value.translation_key == "auth_failed"


# ── alarm panels ────────────────────────────────────────────────────────────

from aiohttp.test_utils import TestServer  # noqa: E402
from homeassistant.components.alarm_control_panel import (  # noqa: E402
    AlarmControlPanelEntityFeature as F,
)
from homeassistant.core import State  # noqa: E402
from homeassistant.exceptions import ServiceValidationError  # noqa: E402

from .fake_controller import FakeController  # noqa: E402


def _panel(hass: HomeAssistant, entity_id: str = ALARM):
    return hass.data["entity_components"]["alarm_control_panel"].get_entity(entity_id)


@pytest.fixture
async def no_details(hass, socket_enabled):
    """An operator who can't read record details: every area might hold zones."""
    fake = FakeController(permit_details=False)
    fake.clock = dt_util.now().replace(tzinfo=None, microsecond=0)
    server = TestServer(fake.app, host="127.0.0.1")
    await server.start_server()
    fake.host = f"127.0.0.1:{server.port}"
    yield fake
    await server.close()


async def test_blocked_modes_hide_features(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    panel = _panel(hass)
    entry.runtime_data.coordinator.blocked_modes[16] = {"away", "home", "night"}
    features = panel.supported_features
    assert not features & (F.ARM_AWAY | F.ARM_VACATION | F.ARM_HOME | F.ARM_NIGHT)


async def test_vacation_survives_a_restart(hass: HomeAssistant, controller) -> None:
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    mock_restore_cache(hass, [State(ALARM, "armed_vacation")])
    controller.state.areas[16] = [128, 129, 0, 0]
    entry = _entry(controller)
    await _setup(hass, entry)
    assert _state(hass, ALARM) == "armed_vacation"


async def test_panel_without_status_and_renames(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    panel = _panel(hass)
    entry.runtime_data.coordinator.data.areas.pop(16)
    assert panel.alarm_state is None
    assert panel.extra_state_attributes == {}

    alarmo = MagicMock()
    entry.runtime_data.alarmo = alarmo
    panel.async_entity_id_changed("alarm_control_panel.old_name")
    await hass.async_block_till_done()
    alarmo.async_restart.assert_called_once()


async def test_unexpected_arm_error_forgets_the_request(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    panel = _panel(hass)
    with (
        patch.object(panel, "_arm_now", AsyncMock(side_effect=RuntimeError("bug"))),
        pytest.raises(RuntimeError),
    ):
        await panel.async_alarm_arm_vacation()
    assert panel._requested is None


async def test_night_off_refuses_night(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, night_mode={"16": "off"})
    await _setup(hass, entry)
    panel = _panel(hass)
    with pytest.raises(ServiceValidationError):
        await panel.async_alarm_arm_night()
    with pytest.raises(ServiceValidationError):
        await panel.async_sync_to("night")
    with pytest.raises(ServiceValidationError):
        panel.check_mode_available("night")
    panel.area.stay_enabled = False
    with pytest.raises(ServiceValidationError):
        await panel.async_sync_to("home")
    with pytest.raises(ServiceValidationError):
        panel.check_mode_available("home")
    assert panel.controller_mode_for("night") == "off"
    assert panel.controller_mode_for("away") == "away"


async def test_following_alarmo(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    panel = _panel(hass)
    for target, expected in (
        ("home", "armed_home"),
        ("disarmed", "disarmed"),
        ("night", "armed_night"),
        ("disarmed", "disarmed"),
        ("vacation", "armed_vacation"),
        ("disarmed", "disarmed"),
        ("away", "armed_away"),
    ):
        await panel.async_sync_to(target)
        await hass.async_block_till_done()
        assert _state(hass, ALARM) == expected, target
    await panel.async_silence()


async def test_set_user_enabled_unchanged_is_a_no_op(hass: HomeAssistant, controller) -> None:
    user = await hass.async_add_executor_job(make_user, "Cleaner", "2468")
    entry = _entry(controller, users=[user])
    await _setup(hass, entry)
    with patch.object(hass.config_entries, "async_update_entry") as update:
        await hass.services.async_call(
            DOMAIN, "set_user_enabled",
            {"entity_id": ALARM, "user": "cleaner", "enabled": True}, blocking=True,
        )
    update.assert_not_called()


async def test_all_areas_panel(hass: HomeAssistant, no_details) -> None:
    entry = _entry(no_details)
    await _setup(hass, entry)
    all_areas = next(
        s.entity_id for s in hass.states.async_all("alarm_control_panel")
        if s.entity_id not in (ALARM, "alarm_control_panel.system_area")
    )
    panel = _panel(hass, all_areas)
    assert panel.code_format is None
    assert panel.supported_features & F.ARM_AWAY

    for service, expected in (
        ("alarm_arm_home", "armed_home"),
        ("alarm_disarm", "disarmed"),
        ("alarm_arm_night", "armed_night"),
        ("alarm_disarm", "disarmed"),
        ("alarm_arm_vacation", "armed_vacation"),
        ("alarm_disarm", "disarmed"),
        ("alarm_arm_away", "armed_away"),
    ):
        await hass.services.async_call(
            "alarm_control_panel", service, {"entity_id": all_areas}, blocking=True
        )
        await hass.async_block_till_done()
        assert _state(hass, all_areas) == expected, service
    # Already armed: arming again leaves every area alone.
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": all_areas}, blocking=True
    )

    # One area refusing still tries the rest, then reports it.
    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": all_areas}, blocking=True
    )
    with (
        patch.object(
            entry.runtime_data.client, "arm_area",
            AsyncMock(side_effect=ProtegeConnectionError("gone")),
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            "alarm_control_panel", "alarm_arm_away", {"entity_id": all_areas}, blocking=True
        )

    # Every area switched off: nothing to offer.
    with patch.object(type(panel), "_areas", lambda _self: []):
        assert panel.supported_features == F(0)


# ── Alarmo sync, unit level ─────────────────────────────────────────────────

from types import SimpleNamespace  # noqa: E402

from homeassistant.core import Context, Event  # noqa: E402

from custom_components.protege_wx import alarmo as alarmo_mod  # noqa: E402

ALARMO_ID = "alarm_control_panel.alarmo"


def _sync(hass: HomeAssistant, area=None, **options) -> alarmo_mod.AlarmoSync:
    entry = SimpleNamespace(
        options={"alarmo_entity": ALARMO_ID, "alarmo_area": 16, **options},
        runtime_data=SimpleNamespace(areas={16: area} if area else {}),
    )
    return alarmo_mod.AlarmoSync(hass, entry)


def test_alarmo_targets() -> None:
    assert alarmo_mod._target(None) is None
    assert alarmo_mod._target(State(ALARMO_ID, "triggered")) is None
    assert alarmo_mod._target(State(ALARMO_ID, "arming", {"arm_mode": "armed_home"})) == "home"
    assert alarmo_mod._target(State(ALARMO_ID, "arming", {"arm_mode": "armed_custom"})) == "custom"
    assert alarmo_mod._target(State(ALARMO_ID, "arming")) is None


async def test_alarmo_sync_without_its_area(hass: HomeAssistant, caplog) -> None:
    sync = _sync(hass)
    sync.async_start()
    assert "isn't set up" in caplog.text
    sync.async_restart()
    sync._reconcile()
    sync._on_change(Event("state_changed", {"entity_id": ALARMO_ID}))
    await sync._to_protege("away")
    sync.async_stop()


async def test_alarmo_resetting_itself_is_ignored(hass: HomeAssistant) -> None:
    area = SimpleNamespace(entity_id=ALARM, async_sync_to=AsyncMock())
    sync = _sync(hass, area)
    hass.states.async_set(ALARM, "armed_away")
    sync._on_change(Event("state_changed", {
        "entity_id": ALARMO_ID,
        "old_state": State(ALARMO_ID, "triggered"),
        "new_state": State(ALARMO_ID, "disarmed", context=Context()),
    }))
    await hass.async_block_till_done()
    area.async_sync_to.assert_not_awaited()


async def test_alarmo_calls_with_code_and_its_own_arm_action(hass: HomeAssistant, caplog) -> None:
    sync = _sync(hass, SimpleNamespace(entity_id=ALARM), alarmo_code="1357")
    calls: list[tuple[str, str, dict]] = []

    async def _record(call) -> None:
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("alarmo", "arm", _record)
    hass.services.async_register("alarm_control_panel", "alarm_disarm", _record)
    await sync._to_alarmo("night")
    await sync._to_alarmo("disarmed")
    assert calls[0] == ("alarmo", "arm", {
        "entity_id": ALARMO_ID, "code": "1357", "mode": "night", "skip_delay": True, "force": True,
    })
    assert calls[1] == ("alarm_control_panel", "alarm_disarm", {
        "entity_id": ALARMO_ID, "code": "1357",
    })

    async def _refuse(call) -> None:
        raise HomeAssistantError("wrong code")

    hass.services.async_register("alarmo", "arm", _refuse)
    await sync._to_alarmo("away")
    assert "couldn't set" in caplog.text


# ── arm when ready ──────────────────────────────────────────────────────────

from custom_components.protege_wx import arm_when_ready as awr  # noqa: E402


def test_night_mode_falls_back_to_off() -> None:
    area = SimpleNamespace(stay_enabled=False, instant_enabled=False)
    assert awr.night_mode_for(area, "stay") == "off"
    assert awr.night_mode_for(area, "instant") == "off"
    assert awr.night_mode_for(SimpleNamespace(stay_enabled=True), "stay") == "stay"


async def _waiting(hass: HomeAssistant, controller):
    entry = _entry(controller)
    await _setup(hass, entry)
    controller.open_input(5)  # Up Passage: open in every mode
    await _refresh(hass, entry)
    waits = entry.runtime_data.arm_when_ready
    panel = _panel(hass)
    await waits.async_begin(panel, "away", 5, "Test")
    assert waits.waiting(16)
    return entry, waits, panel


async def test_arm_when_ready_begin_edges(hass: HomeAssistant, controller) -> None:
    entry, waits, panel = await _waiting(hass, controller)
    waits._waits[16].busy = True
    with pytest.raises(HomeAssistantError) as err:
        await waits.async_begin(panel, "away", 5)
    assert err.value.translation_key == "arm_when_ready_busy"
    waits._waits[16].busy = False

    controller.state.areas[16] = [128, 129, 0, 0]  # armed
    await _refresh(hass, entry)
    await waits.async_begin(panel, "away", 5)  # nothing to wait for
    assert not waits.waiting(16)


async def test_arm_when_ready_readiness_edges(hass: HomeAssistant, controller) -> None:
    entry, waits, panel = await _waiting(hass, controller)
    coordinator = entry.runtime_data.coordinator
    status = coordinator.data.areas[16]
    coordinator.data.areas[16] = SimpleNamespace(known=True, state="bypass_error")
    assert not waits._ready(16, "away", panel)
    coordinator.data.areas.pop(16)
    assert not waits._ready(16, "away", panel)
    waits._on_update()  # no status: skipped, still waiting
    assert waits.waiting(16)
    coordinator.data.areas[16] = status


async def test_arm_when_ready_cancelled_by_an_alarm(hass: HomeAssistant, controller) -> None:
    entry, waits, _panel_ = await _waiting(hass, controller)
    controller.state.areas[16] = [128, 0, 2, 0]  # siren sounding
    await _refresh(hass, entry)
    assert not waits.waiting(16)


async def test_arm_when_ready_without_runtime(hass: HomeAssistant, controller) -> None:
    entry, waits, panel = await _waiting(hass, controller)
    with patch.object(entry, "runtime_data", None):
        waits._on_update()
    entry.runtime_data.areas.pop(16)
    waits.async_stop()  # its panel is gone: just forget the wait
    assert not waits.waiting(16)
    entry.runtime_data.areas[16] = panel


async def test_arm_when_ready_arm_outcomes(hass: HomeAssistant, controller) -> None:
    entry, waits, panel = await _waiting(hass, controller)
    controller.state.inputs[5][0] = 0  # ready now
    await _refresh(hass, entry)
    await hass.async_block_till_done()
    assert _state(hass, ALARM) == "armed_away"
    controller.state.areas[16] = [128, 0, 0, 0]
    await _refresh(hass, entry)

    def refuse(key: str):
        err = HomeAssistantError("no")
        err.translation_key = key
        return AsyncMock(side_effect=err)

    controller.open_input(5)  # open again: every new wait has to wait
    await _refresh(hass, entry)
    ready = patch.object(waits, "_ready", return_value=True)

    async def attempt(arm) -> None:
        await waits.async_begin(panel, "away", 5)
        with ready, patch.object(panel, "async_arm_mode", arm):
            await waits._try(panel, waits._waits[16])

    # Not confirmed yet: keep waiting for the next update.
    await attempt(refuse("arm_unconfirmed"))
    assert waits.waiting(16)
    # A zone opened again in between: keep waiting, up to three times.
    for _ in range(awr._MAX_REFUSALS - 1):
        wait = waits._waits[16]
        with ready, patch.object(panel, "async_arm_mode", refuse("failed_to_arm")):
            await waits._try(panel, wait)
        assert waits.waiting(16)
    with ready, patch.object(panel, "async_arm_mode", refuse("failed_to_arm")):
        await waits._try(panel, waits._waits[16])
    assert not waits.waiting(16)
    # Any other refusal ends the wait.
    await attempt(refuse("auth_failed"))
    assert not waits.waiting(16)

    # Cancelled while it was trying: the cancel lands once the try fails.
    await waits.async_begin(panel, "away", 5)
    wait = waits._waits[16]

    async def cancel_then_fail(_mode: str) -> None:
        waits._finish(panel, awr.RESULT_CANCELLED)
        assert wait.pending == awr.RESULT_CANCELLED
        raise HomeAssistantError("no")

    with ready, patch.object(panel, "async_arm_mode", cancel_then_fail):
        await waits._try(panel, wait)
    assert not waits.waiting(16)

    # Replaced while it was trying: the old try leaves the new wait alone.
    await waits.async_begin(panel, "away", 5)
    old = waits._waits[16]

    async def replaced(_mode: str) -> None:
        waits._end(16)
        waits._waits[16] = awr._Wait("away", 5, dt_util.utcnow(), None)
        raise HomeAssistantError("no")

    with ready, patch.object(panel, "async_arm_mode", replaced):
        await waits._try(panel, old)
    assert waits.waiting(16) and waits._waits[16] is not old
    await waits._try(panel, old)  # stale: ignored

    # Already trying: a second try waits its turn.
    wait = waits._waits[16]
    wait.busy = True
    await waits._try(panel, wait)
    wait.busy = False

    # A crash still clears the busy flag.
    with (
        ready,
        patch.object(panel, "async_arm_mode", AsyncMock(side_effect=RuntimeError("bug"))),
        pytest.raises(RuntimeError),
    ):
        await waits._try(panel, wait)
    assert wait.busy is False

    with patch.object(waits, "_ready", return_value=False):
        await waits._try(panel, waits._waits[16])  # not ready after all
    waits._finish(panel, awr.RESULT_CANCELLED, force=True)
    waits._finish(panel, awr.RESULT_CANCELLED)  # nothing left to finish
    assert not waits.waiting(16)


# ── triggers ────────────────────────────────────────────────────────────────

from custom_components.protege_wx import trigger as trig  # noqa: E402

needs_triggers = pytest.mark.skipif(not trig.SUPPORTED, reason="no entity triggers")


def _trigger(cls, **options):
    instance = cls.__new__(cls)
    instance._options = options
    instance._target = {}
    return instance


async def test_event_entity_kind(hass: HomeAssistant) -> None:
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    other = registry.async_get_or_create("event", "demo", "x_door_1_events")
    sensor = registry.async_get_or_create("sensor", DOMAIN, "x_door_1_events")
    odd = registry.async_get_or_create("event", DOMAIN, "x_door_1_log")
    nothing = registry.async_get_or_create("event", DOMAIN, "x_output_1_events")
    assert trig.event_entity_kind(hass, "event.missing") is None
    assert trig.event_entity_kind(hass, other.entity_id) is None
    assert trig.event_entity_kind(hass, sensor.entity_id) is None
    assert trig.event_entity_kind(hass, odd.entity_id) is None
    assert trig.event_entity_kind(hass, nothing.entity_id) is None


@needs_triggers
def test_trigger_matching_and_wording() -> None:
    granted = _trigger(trig.AccessGrantedTrigger, people=["Jane Citizen", " "], method="pin")
    assert not granted.matches("access_denied", {})
    assert not granted.matches("access_granted", {"user": "Sam", "method": "pin"})
    assert granted.matches("access_granted", {"by": "jane citizen", "method": "pin"})
    assert not granted.matches("access_granted", {"user": "Jane Citizen", "method": "card"})
    assert granted.describe("Front Door", {}) == "Front Door: access granted to someone"

    denied = _trigger(trig.AccessDeniedTrigger)
    assert denied.matches("access_denied", {})
    assert denied.describe("Gate", {}) == "Gate: access denied"

    alert = _trigger(trig.DoorAlertTrigger, alerts=["left_open"])
    assert alert.matches("left_open", {}) and not alert.matches("forced_open", {})
    assert alert.describe("Gate", {"event_type": "forced_open"}) == "Gate: forced open"
    assert alert.describe("Gate", {"event_type": "left_open"}) == "Gate: left open"

    failed = _trigger(trig.FailedToArmTrigger)
    assert failed.matches("failed_to_arm", {})
    assert failed.describe("Alarm", {}) == "Alarm: failed to arm"

    emergency = _trigger(trig.EmergencyTrigger, types=["panic"])
    assert emergency.matches("panic", {}) and not emergency.matches("duress", {})
    assert emergency.describe("Controller", {"event_type": "panic"}) == "panic alarm"

    base = _trigger(trig._EventTrigger)
    with pytest.raises(NotImplementedError):
        base.matches("x", {})
    assert base.describe("Thing", {"event_type": "x"}) == "Thing: x"


@needs_triggers
async def test_trigger_skips_non_changes(hass: HomeAssistant) -> None:
    denied = _trigger(trig.AccessDeniedTrigger)
    denied._hass = hass
    captured = {}

    def _track(_hass, _target, action, _filter):
        captured["action"] = action
        captured["filter"] = _filter
        return lambda: None

    with patch.object(trig, "async_track_target_selector_state_change_event", _track):
        await denied.async_attach_runner(run := MagicMock())
    assert captured["filter"]({"event.gate_events"}) == set()

    def change(old, new):
        event = SimpleNamespace(data={"old_state": old, "new_state": new}, context=Context())
        captured["action"](SimpleNamespace(state_change_event=event))

    stamp = "2026-11-20T10:00:00+00:00"
    before = State("event.gate", stamp, {"event_type": "access_denied"})
    change(None, before)
    change(before, None)
    change(before, State("event.gate", "unavailable"))
    change(State("event.gate", "unavailable"), before)
    change(before, State("event.gate", stamp, {"event_type": "access_denied"}))
    later = "2026-11-20T10:01:00+00:00"
    change(before, State("event.gate", later, {"event_type": "access_granted"}))
    run.assert_not_called()
    change(before, State("event.gate", later, {"event_type": "access_denied"}))
    run.assert_called_once()


# ── users and visitor unlocks ───────────────────────────────────────────────

from datetime import datetime  # noqa: E402

from custom_components.protege_wx import users as users_mod  # noqa: E402


def test_schedules() -> None:
    tz = dt_util.get_default_time_zone()
    monday_late = datetime(2026, 11, 16, 23, 0, tzinfo=tz)
    tuesday_early = datetime(2026, 11, 17, 5, 0, tzinfo=tz)
    tuesday_noon = datetime(2026, 11, 17, 12, 0, tzinfo=tz)
    night_shift = {"from_time": "22:00:00", "until_time": "06:00:00", "days": ["mon"]}
    assert users_mod.access_problem(night_shift, monday_late) is None
    assert users_mod.access_problem(night_shift, tuesday_early) is None  # Monday's shift
    assert users_mod.access_problem(night_shift, tuesday_noon) == "outside_schedule"
    garbled = {"from_time": "late", "expires": "soon", "days": ["mon"]}
    assert users_mod.access_problem(garbled, monday_late) is None
    assert users_mod.access_problem(garbled, tuesday_noon) == "outside_schedule"

    assert users_mod.describe_schedule({}) is None
    assert users_mod.describe_schedule(
        {"days": ["mon", "tue"], "until_time": "17:00:00", "expires": "2026-12-31",
         "enabled": False}
    ) == "mon, tue 00:00-17:00 until 2026-12-31 disabled"
    assert users_mod.describe_schedule({"from_time": "08:00:00"}) == "08:00-24:00"


def test_legacy_code_mismatch_and_disabled_users() -> None:
    codes = users_mod.UserCodes({"panel_code": "2580"})
    assert codes.check("1111", "disarm").reason == "invalid_code"
    user = make_user("Cleaner", "1357")
    user["enabled"] = False
    codes = users_mod.UserCodes({"users": [user]})
    check = codes.check("1357", "disarm")
    assert check.reason == "user_disabled" and check.user == "Cleaner"
    user = make_user("Kid", "2468", can_disarm=False)
    assert users_mod.UserCodes({"users": [user]}).check("2468", "disarm").reason == "not_permitted"


async def test_visitor_unlocks_edges(hass: HomeAssistant, controller, hass_storage, caplog) -> None:
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    entry = _entry(controller)
    soon = (dt_util.utcnow() + timedelta(minutes=5)).isoformat()
    hass_storage[f"{DOMAIN}.{entry.entry_id}.visitor"] = {
        "version": 1, "key": f"{DOMAIN}.{entry.entry_id}.visitor",
        "data": {"doors": {"99": soon, "0": "not a time"}},
    }
    await _setup(hass, entry)
    visitors = entry.runtime_data.visitors
    assert visitors.until == {}  # a door that's gone and a garbled time are skipped

    for minutes in (2, 3):  # a second unlock replaces the first timer
        await hass.services.async_call(
            DOMAIN, "visitor_unlock", {"entity_id": "lock.front_door", "minutes": minutes},
            blocking=True,
        )
    assert len(visitors._timers) == 1

    visitors._on_update()  # the same reading again: nothing to do
    client = entry.runtime_data.client
    with patch.object(client, "lock_door", AsyncMock(side_effect=ProtegeConnectionError("x"))):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=4))
        await hass.async_block_till_done()
    assert "retrying" in caplog.text
    assert 0 in visitors.until and 0 in visitors._timers
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
    await hass.async_block_till_done()
    assert 0 not in visitors.until


# ── switches and binary sensors ─────────────────────────────────────────────

FAULT = "binary_sensor.protege_wx_controller_alarm_fault"


def _entity(hass: HomeAssistant, entity_id: str):
    domain = entity_id.split(".")[0]
    return hass.data["entity_components"][domain].get_entity(entity_id)


async def test_only_outputs_pulse(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, outputs=["120"])
    await _setup(hass, entry)
    for switch in (
        "switch.front_door_hold_open", "switch.alarm_walk_test",
        "switch.alarm_arm_when_ready", "switch.alarm_allow_arm_away",
    ):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "pulse_output", {"entity_id": switch, "seconds": 2}, blocking=True
            )


async def test_output_and_walk_test_switches(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller, outputs=["120"])
    await _setup(hass, entry)
    output = "switch.garage_door_open_close"
    for service in ("turn_on", "turn_off"):
        await hass.services.async_call("switch", service, {"entity_id": output}, blocking=True)
    assert controller.state.commands[-1].endswith("Command=0") or "PGM" in controller.state.commands[-1]
    entry.runtime_data.coordinator.data.outputs.pop(120)
    assert _entity(hass, output).extra_state_attributes == {}

    walk = "switch.alarm_walk_test"
    await hass.services.async_call("switch", "turn_on", {"entity_id": walk}, blocking=True)
    assert _state(hass, walk) == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": walk}, blocking=True)
    assert _state(hass, walk) == "off"

    allow = "switch.alarm_allow_arm_away"
    await hass.services.async_call("switch", "turn_off", {"entity_id": allow}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": allow}, blocking=True)
    assert _state(hass, allow) == "on"


async def test_arm_when_ready_switch_credits_the_user(
    hass: HomeAssistant, controller, hass_admin_user
) -> None:
    from homeassistant.core import Context as Ctx

    entry = _entry(controller)
    await _setup(hass, entry)
    controller.open_input(5)
    await _refresh(hass, entry)
    switch = "switch.alarm_arm_when_ready"
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch}, blocking=True,
        context=Ctx(user_id=hass_admin_user.id),
    )
    assert _state(hass, switch) == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)

    panel = entry.runtime_data.areas.pop(16)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    entry.runtime_data.areas[16] = panel

    entity = _entity(hass, switch)
    with patch.object(hass.auth, "async_get_user", AsyncMock(return_value=None)):
        entity._context = Ctx(user_id="gone")
        assert await entity._user_name() is None


async def test_fault_sensor_unknowns(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    troubles = entry.runtime_data.coordinator.data.trouble_inputs
    troubles[225] = SimpleNamespace(known=False, is_open=None)
    assert _entity(hass, FAULT).is_on is None
    troubles.clear()
    assert _entity(hass, FAULT).is_on is None
    entry.runtime_data.coordinator.data.inputs.pop(1)
    assert _entity(hass, "binary_sensor.foyer").extra_state_attributes == {}


class _DoorPositionController(FakeController):
    """The front door has a door-position (reed) input."""

    def _command(self, plain: str, sessid: str) -> str:
        reply = super()._command(plain, sessid)
        return reply.replace("DoorId=0&DoorPositionInput=2147483647", "DoorId=0&DoorPositionInput=1")


async def test_door_position_sensor(hass: HomeAssistant, socket_enabled) -> None:
    fake = _DoorPositionController()
    fake.clock = dt_util.now().replace(tzinfo=None, microsecond=0)
    server = TestServer(fake.app, host="127.0.0.1")
    await server.start_server()
    fake.host = f"127.0.0.1:{server.port}"
    try:
        entry = _entry(fake)
        await _setup(hass, entry)
        sensor = next(
            s.entity_id for s in hass.states.async_all("binary_sensor")
            if s.attributes.get("device_class") == "door"
        )
        assert _state(hass, sensor) in ("off", "on")
        assert "controller_state" in hass.states.get(sensor).attributes
        entry.runtime_data.coordinator.data.doors.pop(0)
        entity = _entity(hass, sensor)
        assert entity.is_on is None and entity.extra_state_attributes == {}
        assert entity.available is False
        await hass.config_entries.async_unload(entry.entry_id)
    finally:
        await server.close()


# ── coordinator ─────────────────────────────────────────────────────────────

from custom_components.protege_wx import coordinator as coord  # noqa: E402


def test_pin_guard_forgets_old_failures() -> None:
    guard = coord.PinGuard()
    with patch.object(coord.time, "monotonic", return_value=1000.0):
        guard.record_failure()
    with patch.object(coord.time, "monotonic", return_value=1000.0 + guard.WINDOW + 1):
        guard.record_failure()
    assert len(guard._failures) == 1


async def test_discovery_tolerates_refusals() -> None:
    client = MagicMock()
    client.list_records = AsyncMock(side_effect=ProtegeError("refused"))
    client.get_record = AsyncMock(side_effect=ProtegeError("refused"))
    assert await coord._names(client, "GXT_AREAS_TBL") == {}
    assert await coord._detail(client, "GXT_AREAS_TBL", 1) == {}
    client.list_records = AsyncMock(side_effect=ProtegeAuthError("logged out"))
    client.get_record = AsyncMock(side_effect=ProtegeAuthError("logged out"))
    with pytest.raises(ProtegeAuthError):
        await coord._names(client, "GXT_AREAS_TBL")
    with pytest.raises(ProtegeAuthError):
        await coord._detail(client, "GXT_AREAS_TBL", 1)
    client.health_values = AsyncMock(side_effect=ProtegeAuthError("logged out"))
    with pytest.raises(ProtegeAuthError):
        await coord.async_discover(client)


async def test_discovery_without_health(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    with patch(
        "aioprotegewx.ProtegeClient.health_values", AsyncMock(side_effect=ProtegeError("no"))
    ):
        await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.site.serial in (None, "")


async def test_coordinator_odds_and_ends(hass: HomeAssistant, controller, caplog) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    coordinator = entry.runtime_data.coordinator
    site = coordinator.site
    assert site.input_by_name("Study").id == 2
    assert site.input_by_name("Nowhere") is None

    assert coordinator.input_area_armed(99) is True  # unknown input: assume armed
    data = coordinator.data
    coordinator.data = None
    assert coordinator.input_area_armed(2) is True
    assert coordinator.zones_known(16) is False
    coordinator.data = data

    data.health["NetworkVoltage"] = "n/a"
    assert coordinator._fresh_voltage(data, coordinator._health_read_at) is None

    def broken(_event) -> None:
        raise RuntimeError("listener bug")

    seen: list = []
    coordinator.async_add_event_listener(broken)
    coordinator.async_add_event_listener(seen.append)
    controller.log("Area Alarm Armed By Home Assistant")
    await _refresh(hass, entry)
    assert seen and "Error handling Protege event" in caplog.text


async def test_reading_back_older_event_pages(hass: HomeAssistant, controller) -> None:
    entry = _entry(controller)
    await _setup(hass, entry)
    coordinator = entry.runtime_data.coordinator
    client = entry.runtime_data.client
    real = client.events

    async def newest_only(page: str = "Latest"):
        if page == "Previous":
            raise ProtegeConnectionError("gone")
        return await real(page)

    for _ in range(25):  # more than a page of news since the last read
        controller.log("User Jane Citizen Entry Granted Front Door Using User By Pin")
    with patch.object(client, "events", newest_only):
        fresh = await coordinator._read_events()
    assert fresh

    async def empty_previous(page: str = "Latest"):
        return [] if page == "Previous" else await real(page)

    with patch.object(client, "events", empty_previous):
        assert await coordinator._read_events()

    async def auth_previous(page: str = "Latest"):
        if page == "Previous":
            raise ProtegeAuthError("logged out")
        return await real(page)

    with patch.object(client, "events", auth_previous), pytest.raises(ProtegeAuthError):
        await coordinator._read_events()
