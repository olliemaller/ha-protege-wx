"""Smoke test against a real, installed Home Assistant (no test harness).

Boots a bare Home Assistant core in a throwaway config folder, the same way
its own startup does (registries, config entries, the trigger and condition
helpers), with this integration as a custom component. Then it adds the fake
controller through the setup flow, arms and disarms, uses "Arm when ready",
and, where the version has them, fires an automation built from this
integration's own trigger and condition.

Used in CI against the newest release and the beta, which the pytest harness
doesn't cover yet. Exits non-zero on failure.

    python tests/smoke.py
"""
from __future__ import annotations

import asyncio
import pathlib
import shutil
import sys
import tempfile
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent

AUTOMATION = {
    "id": "smoke",
    "alias": "Smoke",
    "triggers": [
        {"trigger": "protege_wx.access_granted", "target": {"entity_id": "event.front_door_events"}}
    ],
    "conditions": [
        {"condition": "protege_wx.ready_to_arm", "target": {"entity_id": "alarm_control_panel.alarm"}}
    ],
    "actions": [{"event": "smoke_fired"}],
}


async def run(config_dir: pathlib.Path, steps: list[str]) -> None:
    import homeassistant  # noqa: F401  (sets up its module aliases first)
    from aiohttp.test_utils import TestServer
    from homeassistant import bootstrap, config_entries, loader
    from homeassistant.const import __version__
    from homeassistant.core import HomeAssistant
    from homeassistant.setup import async_setup_component

    sys.path.insert(0, str(ROOT))
    from tests.fake_controller import FakeController

    steps.append(f"Home Assistant {__version__}")
    fake = FakeController()
    fake.log("Area Alarm Disarmed By Home Assistant")
    server = TestServer(fake.app, host="127.0.0.1")
    await server.start_server()

    hass = HomeAssistant(str(config_dir))
    hass.config.skip_pip = True
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    loader.async_setup(hass)
    sys.path.insert(0, str(config_dir))  # where custom_components lives
    # Returns False on a storage version problem (None before 2026).
    assert await bootstrap.async_load_base_functionality(hass) is not False
    try:
        assert await async_setup_component(hass, "homeassistant", {})
        await hass.async_start()

        flow = await hass.config_entries.flow.async_init(
            "protege_wx", context={"source": config_entries.SOURCE_USER}
        )
        flow = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {"host": f"127.0.0.1:{server.port}", "username": "Home Assistant", "password": "secret"},
        )
        if flow["type"] == "menu":
            flow = await hass.config_entries.flow.async_configure(
                flow["flow_id"], {"next_step_id": "continue_anyway"}
            )
        assert flow["type"] == "create_entry", flow
        await hass.async_block_till_done()
        steps.append("set up through the flow")

        def state(entity_id: str) -> str:
            current = hass.states.get(entity_id)
            assert current is not None, f"{entity_id} missing"
            return current.state

        assert state("alarm_control_panel.alarm") == "disarmed"
        for entity_id in (
            "lock.front_door",
            "switch.alarm_arm_when_ready",
            "select.alarm_arm_when_ready_mode",
            "event.front_door_events",
            "binary_sensor.alarm_ready_to_arm",
        ):
            state(entity_id)
        steps.append("entities created")

        panel = {"entity_id": "alarm_control_panel.alarm"}
        await hass.services.async_call("alarm_control_panel", "alarm_arm_home", panel, blocking=True)
        assert state("alarm_control_panel.alarm") == "armed_home"
        await hass.services.async_call("alarm_control_panel", "alarm_disarm", panel, blocking=True)
        assert state("alarm_control_panel.alarm") == "disarmed"
        steps.append("armed and disarmed")

        fake.open_input(5)
        entry = hass.config_entries.async_entries("protege_wx")[0]
        coordinator = entry.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.alarm_arm_when_ready"}, blocking=True)
        assert state("switch.alarm_arm_when_ready") == "on"
        fake.state.inputs[5][0] = 0
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state("alarm_control_panel.alarm") == "armed_away"
        assert state("switch.alarm_arm_when_ready") == "off"
        await hass.services.async_call("alarm_control_panel", "alarm_disarm", panel, blocking=True)
        steps.append("arm when ready")

        from custom_components.protege_wx import condition, trigger

        if not (trigger.SUPPORTED and condition.SUPPORTED):
            steps.append("triggers and conditions: not on this version")
            return
        fired: list = []
        hass.bus.async_listen("smoke_fired", fired.append)
        assert await async_setup_component(hass, "automation", {"automation": [AUTOMATION]})
        await hass.async_block_till_done()
        fake.log("User Jane Citizen Entry Granted Front Door Using User By Card")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert len(fired) == 1, "access_granted trigger did not fire"
        steps.append("trigger and condition fired")
    finally:
        await hass.async_stop(force=True)
        await server.close()


def main() -> int:
    config_dir = pathlib.Path(tempfile.mkdtemp(prefix="protege-smoke-"))
    shutil.copytree(ROOT / "custom_components/protege_wx", config_dir / "custom_components/protege_wx")
    steps: list[str] = []
    try:
        asyncio.run(asyncio.wait_for(run(config_dir, steps), 180))
    except BaseException:  # noqa: BLE001 - report and fail
        for step in steps:
            print(f"  {step}")
        traceback.print_exc()
        print("Smoke test failed")
        return 1
    finally:
        shutil.rmtree(config_dir, ignore_errors=True)
    for step in steps:
        print(f"  {step}")
    print("Smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
