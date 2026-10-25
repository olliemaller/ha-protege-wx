"""A fake Protege WX web interface for tests.

Speaks the real wire protocol (challenge/response login, AES-encrypted
commands) in either the 2.3.x "post" flavour or the "legacy" GET flavour, and
behaves like the real controller seen on 25 Oct 2026:

* an Away or Instant arm with a non-bypassed zone open fails with
  "Input X Opened" + "Area Alarm Failure To ARM By Home Assistant";
* a Stay arm ignores Stay-type zones (Study, Living, Kitchen, Garage, Foyer);
* force arming bypasses open zones;
* every action is written to an event log with the real line formats.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aiohttp import web

from custom_components.protege_wx.wxapi import crypto

LOCKED_OUT = "FAIL:120"
NAMES = {
    "GXT_AREAS_TBL": {0: "System Area", 16: "Alarm"},
    "GXT_DOORS_TBL": {0: "Front Door", 1: "Gate"},
    "GXT_INPUTS_TBL": {
        0: "Garage", 1: "Foyer", 2: "Study", 3: "Living", 4: "Kitchen",
        5: "Up Passage", 6: "Master Bedroom", 7: "Controller Input 8",
    },
    "GXT_TROUBLEINPUTS_TBL": {
        217: "System Restarted", 225: "Analog Expander 1 Mains Failure",
        226: "Analog Expander 1 Low Battery/Battery Failure",
    },
    "GXT_PGMS_TBL": {112: "Controller Bell 0", 120: "Garage Door Open/Close"},
    "GXT_INPUTTYPES_TBL": {40: "Instant", 42: "Delay", 51: "Stay Instant", 52: "Stay Delay"},
}
# input id -> zone type id (as on the real controller)
ZONE_TYPES = {0: 52, 1: 52, 2: 51, 3: 51, 4: 51, 5: 40, 6: 40}


@dataclass
class FakeState:
    areas: dict[int, list[int]] = field(
        default_factory=lambda: {0: [128, 0, 5, 0], 16: [128, 0, 0, 0]}
    )
    doors: dict[int, list[int]] = field(default_factory=lambda: {0: [0, 0], 1: [0, 0]})
    inputs: dict[int, list[int]] = field(default_factory=lambda: {i: [0, 0] for i in range(8)})
    troubles: dict[int, list[int]] = field(
        default_factory=lambda: {217: [0, 0], 225: [0, 0], 226: [0, 0]}
    )
    outputs: dict[int, list[int]] = field(default_factory=lambda: {112: [0], 120: [0]})
    names: dict[str, dict[int, str]] = field(default_factory=lambda: {k: dict(v) for k, v in NAMES.items()})
    commands: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)


class FakeController:
    """aiohttp application that behaves like PRT_CTRL_DIN_ISAPI.dll."""

    def __init__(
        self,
        username: str = "Home Assistant",
        password: str = "secret",
        *,
        protocol: str = "post",
        permit_details: bool = True,
    ) -> None:
        self.username = username.lower()
        self.pw_sha1 = crypto.sha1_hex(password)
        self.protocol = protocol
        self.permit_details = permit_details
        self.state = FakeState()
        self.sessions: dict[str, dict] = {}
        self.login_failures = 0
        self.init_sessions = 0
        self.lock_out = False
        self.drop_sessions = False
        self.always_invalid = False
        self.bare_fail_logins = False
        self.retry_replies = 0
        self.health_troubles: list[str] = []
        self.voltage_mv = 13566
        self.deny_events = False  # operator without event-log permission
        self.offline = False
        self.exit_delay = 60
        self.entry_delay = 45
        self.clock = datetime(2026, 10, 25, 19, 21, 0)
        self.app = web.Application()
        self.app.router.add_route("*", "/PRT_CTRL_DIN_ISAPI.dll", self._handle)
        self.log("Area Alarm Disarmed By Home Assistant")

    # ── helpers for tests ──────────────────────────────────────────────────

    def log(self, text: str) -> None:
        self.clock += timedelta(seconds=1)
        self.state.events.append(f"Sun {self.clock:%d/%m/%Y %H:%M:%S} {text}")

    def open_input(self, rec: int) -> None:
        self.state.inputs[rec][0] = 1

    # ── transport ──────────────────────────────────────────────────────────

    async def _handle(self, request: web.Request) -> web.Response:
        if self.offline:
            raise web.HTTPServiceUnavailable()
        if self.protocol == "post":
            if request.method != "POST":
                return web.Response(status=405)
            body = (await request.read()).decode("latin-1")
        else:
            if request.method != "GET":
                return web.Response(status=405)
            body = request.query_string
        response = web.Response(text="")
        response.text = self._dispatch(body, request.cookies.get("SESSID"), response)
        return response

    def _dispatch(self, body: str, sessid: str | None, response: web.Response) -> str:
        if body.startswith("Command&Type=Session&SubType=InitSession"):
            self.init_sessions += 1
            if self.protocol == "post":
                sessid = secrets.token_hex(16).upper()
                response.set_cookie("SESSID", sessid)
            else:
                sessid = dict(p.split("=", 1) for p in body.split("&") if "=" in p)["SessionID"]
            seed0 = secrets.randbelow(2**31)
            self.sessions[sessid] = {"seed0": seed0, "key": None}
            return str(seed0)

        if body.startswith("Command&Type=Session&SubType=CloseSession"):
            # Unencrypted close of a half-open session.
            if self.protocol == "legacy":
                sessid = dict(p.split("=", 1) for p in body.split("&") if "=" in p).get("SessionID")
            self.sessions.pop(sessid or "", None)
            return "OK"

        if body.startswith("Command&Type=Session&SubType=CheckPassword"):
            fields = dict(p.split("=", 1) for p in body.split("&") if "=" in p)
            if self.protocol == "legacy":
                sessid = fields.get("SessionID")
            session = self.sessions.get(sessid or "")
            if session is None or self.bare_fail_logins:
                return "FAIL"
            if self.lock_out:
                return LOCKED_OUT
            name, pw = crypto.login_hashes(self.username, self.pw_sha1, session["seed0"])
            if fields.get("Name") != name or fields.get("Password") != pw:
                self.login_failures += 1
                return "FAIL"
            seed1 = secrets.randbelow(2**31)
            session["key"] = crypto.session_key(self.pw_sha1, seed1)
            return str(seed1)

        # Encrypted command
        if self.protocol == "legacy":
            sessid, body = body[:32], body[32:]
        if self.drop_sessions or self.always_invalid:
            self.sessions.clear()
            self.drop_sessions = False
        session = self.sessions.get(sessid or "")
        if session is None or session["key"] is None:
            return "<invalid session> < Packet not Init and not encrypted. >"
        key = session["key"]
        plain = crypto.decrypt(body, key)
        if self.protocol == "legacy":
            assert plain.endswith("&Sequence="), plain
            plain = plain[: -len("&Sequence=")]
        else:
            assert "&Sequence=" not in plain, plain
        if self.retry_replies:
            self.retry_replies -= 1
            return "Command failed (8)"
        reply = self._command(plain, sessid)
        return crypto.encrypt(reply, key)

    # ── commands ───────────────────────────────────────────────────────────

    def _command(self, plain: str, sessid: str) -> str:
        fields = dict(p.split("=", 1) for p in plain.split("&") if "=" in p)
        sub = fields.get("SubType", "")
        if plain.startswith("Command&Type=Session&SubType=CloseSession"):
            self.sessions.pop(sessid, None)
            return "OK"
        if plain.startswith("Request&Type=Events"):
            if self.deny_events:
                return "FAIL"
            page = self.state.events[-20:]
            if not page:
                return "<no response>"
            parts = []
            for i, text in enumerate(page):
                parts.append(f"Event{i}={text}&EventCodes{i}=1,2,3")
            return "&".join(parts)
        if plain.startswith("Request&Type=Health&SubType=Values"):
            return f"SerialNumber=A1B2C3D4&WXVersion=4.00 2510 P048    &NetworkVoltage={self.voltage_mv}&MemTotal=56377344&MemUsed=19759104"
        if plain.startswith("Request&Type=Health&SubType=List"):
            if not self.health_troubles:
                return "<no response>"
            return "&".join(f"Trouble{i}={t}" for i, t in enumerate(self.health_troubles))
        if plain.startswith("Request&Type=List"):
            return "&".join(f"{k}={v}" for k, v in self.state.names.get(sub, {}).items())
        if plain.startswith("Request&Type=Detail"):
            if not self.permit_details:
                return "FAIL"
            rec = int(fields["RecId"])
            if sub == "GXT_INPUTS_TBL":
                if rec == 7:
                    return f"InputId={rec}&Area1=2147483647&ZoneType1=2147483647"
                return f"InputId={rec}&Area1=16&ZoneType1={ZONE_TYPES[rec]}&Area2=2147483647"
            if sub == "GXT_AREAS_TBL":
                return f"AreaId={rec}&EnableStayArming=true&EnableInstantArming=true&ExitDelay={self.exit_delay}&EntryDelay={self.entry_delay}"
            if sub == "GXT_DOORS_TBL":
                return f"DoorId={rec}&DoorPositionInput=2147483647"
            return ""
        if plain.startswith("Request&Type=Status"):
            prefix, records = {
                "GXT_AREAS_TBL": ("Area", self.state.areas),
                "GXT_DOORS_TBL": ("Door", self.state.doors),
                "GXT_INPUTS_TBL": ("Input", self.state.inputs),
                "GXT_TROUBLEINPUTS_TBL": ("TroubleInput", self.state.troubles),
                "GXT_PGMS_TBL": ("PGM", self.state.outputs),
            }[sub]
            parts = [f"{prefix}{k}={','.join(map(str, v))}" for k, v in records.items()]
            parts.append(f"{prefix}2147483647=0,0,0")
            return "&".join(parts)
        if plain.startswith("Command&Type=Control"):
            self.state.commands.append(plain)
            rec, cmd = int(fields["RecId"]), int(fields["Command"])
            return self._control(sub, rec, cmd, fields)
        return "FAIL"

    def _control(self, sub: str, rec: int, cmd: int, fields: dict) -> str:
        if sub == "GXT_AREAS_TBL":
            area = self.state.names["GXT_AREAS_TBL"][rec]
            if cmd == 0:
                self.state.areas[rec][1:3] = [0, 0]
                self.log(f"Area {area} Disarmed By Home Assistant")
                return "OK"
            if cmd == 9:
                self.state.areas[rec][2] &= ~(1 << 1)
                return "OK"
            stay = cmd == 10
            force = cmd in (4, 6)
            open_zones = [
                i for i, (st, flags) in self.state.inputs.items()
                if i in ZONE_TYPES and st != 0 and not flags
                and not (stay and ZONE_TYPES[i] in (51, 52))
            ]
            if open_zones and not force:
                for i in open_zones:
                    self.state.events.append(
                        f"Sun {self.clock + timedelta(seconds=1):%d/%m/%Y %H:%M:%S} "
                        f"Input {self.state.names['GXT_INPUTS_TBL'][i]} Opened"
                    )
                self.log(f"Area {area} Failure To ARM By Home Assistant")
                self.log(f"Area {area} Arming Cancelled By Home Assistant")
                return "OK"
            for i in open_zones:
                self.state.inputs[i][1] = 1
            flags = {3: 0, 4: 1 << 4, 5: 1 << 5, 6: (1 << 5) | (1 << 4), 10: 1 << 6}.get(cmd, 0)
            self.state.areas[rec][1:3] = [128, flags | (1 << 3)]
            mode = {10: "Stay ", 5: "Instant ", 6: "Instant "}.get(cmd, "")
            self.log(f"Area {area} {mode}Armed By Home Assistant")
            return "OK"
        if sub == "GXT_DOORS_TBL":
            name = self.state.names["GXT_DOORS_TBL"][rec]
            self.state.doors[rec][0] = {0: 0, 1: 7, 2: 9}.get(cmd, 7)
            self.log(f"Door {name} {'Locked' if cmd == 0 else 'Unlocked'} By Home Assistant")
            return "OK"
        if sub == "GXT_INPUTS_TBL":
            self.state.inputs[rec][1] = {0: 0, 1: 1, 2: 3}[cmd]
            return "OK"
        if sub == "GXT_PGMS_TBL":
            self.state.outputs[rec][0] = {0: 0, 1: 1, 2: 3}[cmd]
            if cmd == 2:
                assert 1 <= int(fields["Data1"]) <= 65535
            return "OK"
        return "FAIL"
