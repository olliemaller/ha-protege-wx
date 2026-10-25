"""End-to-end tests of the bundled client against the fake controller."""
from __future__ import annotations

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from custom_components.protege_wx.wxapi import (
    PROTOCOL_LEGACY,
    PROTOCOL_POST,
    ProtegeAuthError,
    ProtegeClient,
    ProtegeConnectionError,
    crypto,
    normalise_host,
)
from custom_components.protege_wx.wxapi import client as client_module
from custom_components.protege_wx.wxapi.events import (
    EventParser,
    parse_event_reply,
    parse_line,
)
from custom_components.protege_wx.wxapi.status import parse_areas, parse_inputs

from .fake_controller import FakeController


@pytest.fixture
async def server_factory(socket_enabled):
    servers = []

    async def make(controller: FakeController):
        server = TestServer(controller.app, host="127.0.0.1")
        await server.start_server()
        servers.append(server)
        return f"127.0.0.1:{server.port}"

    yield make
    for server in servers:
        await server.close()


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(client_module, "RETRY_DELAY", 0)


async def _client(host: str, password: str = "secret", **kwargs) -> tuple[ProtegeClient, aiohttp.ClientSession]:
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    return ProtegeClient(session, host, "Home Assistant", password, **kwargs), session


@pytest.mark.parametrize("protocol", [PROTOCOL_POST, PROTOCOL_LEGACY])
async def test_auto_detects_protocol_and_reads_status(server_factory, protocol):
    controller = FakeController(protocol=protocol)
    host = await server_factory(controller)
    client, session = await _client(host)
    try:
        await client.login()
        assert client.protocol == protocol
        areas = await client.area_status()
        assert set(areas) == {0, 16}
        assert areas[0].flags == {"alarm_activated", "alarms_in_memory"}
        assert areas[16].state == "disarmed"
        assert (await client.list_records("GXT_DOORS_TBL")) == {0: "Front Door", 1: "Gate"}
        events = await client.events()
        assert events[-1].text == "Area Alarm Disarmed By Home Assistant"
    finally:
        await client.close()
        await session.close()
    assert controller.sessions == {}


async def test_wrong_password_raises_once_then_latches(server_factory):
    controller = FakeController()
    host = await server_factory(controller)
    client, session = await _client(host, password="wrong")
    try:
        with pytest.raises(ProtegeAuthError):
            await client.login()
        # Later requests must not try again (each failure counts towards lockout).
        with pytest.raises(ProtegeAuthError):
            await client.area_status()
    finally:
        await session.close()
    assert controller.login_failures == 1
    # The half-open session was closed.
    assert controller.sessions == {}


async def test_lockout_seconds_reported(server_factory):
    controller = FakeController()
    controller.lock_out = True
    host = await server_factory(controller)
    client, session = await _client(host)
    try:
        with pytest.raises(ProtegeAuthError) as err:
            await client.login()
        assert err.value.lockout_seconds == 120
    finally:
        await session.close()


async def test_dropped_session_is_re_established(server_factory):
    controller = FakeController()
    host = await server_factory(controller)
    client, session = await _client(host)
    try:
        await client.login()
        controller.drop_sessions = True
        doors = await client.door_status()
        assert doors[0].is_locked is True
    finally:
        await client.close()
        await session.close()


async def test_wedged_controller_backs_off_instead_of_storming(server_factory):
    controller = FakeController()
    host = await server_factory(controller)
    client, session = await _client(host)
    try:
        await client.login()
        controller.always_invalid = True
        for _ in range(20):
            with pytest.raises(ProtegeConnectionError):
                await client.area_status()
    finally:
        await session.close()
    # 1 initial login + 1 re-login, then backing off: no login storm.
    assert controller.init_sessions <= 2


async def test_login_cap(server_factory, monkeypatch):
    controller = FakeController()
    host = await server_factory(controller)
    client, session = await _client(host)
    try:
        for _ in range(client_module.MAX_LOGINS_PER_WINDOW):
            await client.login()
        with pytest.raises(ProtegeConnectionError):
            await client.login()
    finally:
        await session.close()
    assert controller.init_sessions == client_module.MAX_LOGINS_PER_WINDOW


async def test_bare_fail_on_relogin_is_not_a_bad_password(server_factory):
    controller = FakeController()
    host = await server_factory(controller)
    client, session = await _client(host)
    try:
        await client.login()
        controller.drop_sessions = True
        controller.bare_fail_logins = True
        with pytest.raises(ProtegeConnectionError):
            await client.area_status()
        assert not client.auth_failed
        client.guard.backoff_until = 0
        with pytest.raises(ProtegeAuthError):  # a second bare FAIL in a row
            await client.area_status()
        assert client.auth_failed
    finally:
        await session.close()


async def test_command_failed_8_is_retried(server_factory):
    controller = FakeController()
    host = await server_factory(controller)
    client, session = await _client(host)
    try:
        await client.login()
        controller.retry_replies = 2
        assert 16 in await client.area_status()
    finally:
        await client.close()
        await session.close()


async def test_no_login_after_close(server_factory):
    controller = FakeController()
    host = await server_factory(controller)
    client, session = await _client(host)
    try:
        await client.login()
        await client.close()
        with pytest.raises(ProtegeConnectionError):
            await client.area_status()
    finally:
        await session.close()
    assert controller.init_sessions == 1


async def test_controls_change_state(server_factory):
    controller = FakeController()
    host = await server_factory(controller)
    client, session = await _client(host)
    try:
        await client.arm_area(16, "stay")
        area = (await client.area_status())[16]
        assert area.state == "armed" and "partial_armed" in area.flags
        await client.unlock_door(1, latched=True)
        door = (await client.door_status())[1]
        assert door.is_locked is False and door.is_latched is True
        await client.set_bypass(3, "permanent")
        assert (await client.input_status())[3].bypass == "permanent"
        await client.set_output(120, True, seconds=10)
        assert (await client.output_status())[120].is_on
        with pytest.raises(ValueError):
            await client.arm_area(16, "stay", force=True)
    finally:
        await client.close()
        await session.close()
    assert "Command=10" in controller.state.commands[0]


def test_host_normalised():
    assert normalise_host(" http://192.168.1.10:7377/index.htm ") == "192.168.1.10:7377"


def test_crypto_round_trip_and_known_hash():
    key = "0123456789ABCDEF"
    assert crypto.decrypt(crypto.encrypt("Area16=128,0,0,0", key), key) == "Area16=128,0,0,0"
    assert crypto.sha1_hex("abc") == "a9993e364706816aba3e25717850c26c9cd0d89d"
    assert crypto.xor_with_seed("A", 1) == "40"


def test_unknown_codes_are_not_reassuring():
    area = parse_areas("Area16=128,999,0,0")[16]
    assert not area.known
    garbage = parse_inputs("Input3=x,0&Input4=2,0")
    assert garbage[3].is_open is None
    assert garbage[4].is_open is True and garbage[4].is_tampered is True


def test_latched_alarm_flag_is_not_an_active_alarm():
    disarmed_with_memory = parse_areas("Area0=128,0,5,0")[0]
    assert not disarmed_with_memory.in_alarm
    armed_alarm = parse_areas("Area16=128,128,1,0")[16]
    assert armed_alarm.in_alarm
    siren = parse_areas("Area16=128,0,2,0")[16]
    assert siren.in_alarm


REAL_LINES = [
    "Sun 25/10/2026 19:21:35 Area Alarm Stay Arming Started By Home Assistant",
    "Sun 25/10/2026 19:21:35 Output Keypad 1 Green LED OFF By Group PG004",
    "Sun 25/10/2026 19:21:06 Input Living Opened",
    "Sun 25/10/2026 19:21:06 Area Alarm Failure To ARM By Home Assistant",
    "Sun 25/10/2026 19:21:32 Area Alarm Instant Armed By Home Assistant",
    "Sun 25/10/2026 15:34:50 User Jane Citizen Entry Granted Front Door Using User By Pin",
    "Sun 25/10/2026 15:34:50 Door Gate Unlocked By Door Front Door",
    "Sun 25/10/2026 18:38:56 Trouble Input System Restarted Opened",
    "Sun 25/10/2026 18:38:47 System Power Up",
]


def test_event_parsing_of_real_lines():
    parser = EventParser(["Alarm", "System Area"], ["Front Door", "Gate"], ["Living"], ["System Restarted"])
    parsed = [parser.parse(parse_line(line)) for line in REAL_LINES]
    summary = [(p.kind, p.subject, p.event_type, p.by, p.mode) for p in parsed]
    assert summary == [
        ("area", "Alarm", "arming_started", "Home Assistant", "stay"),
        ("noise", None, "other", None, None),
        ("input", "Living", "opened", None, None),
        ("area", "Alarm", "failed_to_arm", "Home Assistant", None),
        ("area", "Alarm", "armed", "Home Assistant", "instant"),
        ("access", "Front Door", "access_granted", "Jane Citizen", None),
        ("door", "Gate", "unlocked", "Door Front Door", None),
        ("trouble", "System Restarted", "trouble", None, None),
        ("system", None, "power_up", None, None),
    ]
    assert parsed[5].method == "pin"


def test_event_pages_sorted_by_time():
    reply = "&".join(f"Event{i}={line}&EventCodes{i}=1" for i, line in enumerate(REAL_LINES))
    times = [e.time for e in parse_event_reply(reply)]
    assert times == sorted(times)
