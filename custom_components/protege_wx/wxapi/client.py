"""Async client for the Protege WX web-programming endpoint.

The controller's built-in web interface talks to ``/PRT_CTRL_DIN_ISAPI.dll``.
Two wire protocols exist, and this client detects which one a controller uses:

``post`` (web UI 2.3.x, e.g. 2.3.628)
    Every request is an HTTP POST with the command in the body. InitSession
    takes no session ID; the controller issues a ``SESSID`` cookie. Encrypted
    commands are sent as-is, with no session prefix and no sequence suffix.

``legacy`` (older web UI)
    HTTP GET with the command as the query string. The client invents the
    32-hex session ID, passes it to InitSession and CheckPassword, sends it as
    the ``SESSID`` cookie and prefixes every encrypted command with it.
    Encrypted payloads carry an empty ``&Sequence=`` suffix.

Protecting the controller matters more than retrying quickly. A controller
whose session table filled with abandoned sessions has been seen to stop
answering and reboot, and failed logins count towards an operator lockout. So:

* only one request is in flight at a time, as with the web UI;
* a dropped session is re-established once; if a fresh session is rejected
  straight away, the client backs off (30 s doubling to 10 min);
* at most ``MAX_LOGINS_PER_WINDOW`` logins happen per ``LOGIN_WINDOW``;
* a rejected password latches: no further login is attempted until a new
  client is created (the integration reloads after re-authentication);
* half-open sessions are closed, and nothing logs in after ``close()``.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections import deque

import aiohttp
from yarl import URL

from . import crypto
from .events import ProtegeEvent, parse_event_reply
from .status import (
    AreaStatus,
    DoorStatus,
    InputStatus,
    OutputStatus,
    parse_areas,
    parse_doors,
    parse_inputs,
    parse_outputs,
)

_LOGGER = logging.getLogger(__name__)

ENDPOINT = "PRT_CTRL_DIN_ISAPI.dll"
PROTOCOL_AUTO = "auto"
PROTOCOL_POST = "post"
PROTOCOL_LEGACY = "legacy"
PROTOCOLS = (PROTOCOL_AUTO, PROTOCOL_POST, PROTOCOL_LEGACY)

TBL_AREAS = "GXT_AREAS_TBL"
TBL_DOORS = "GXT_DOORS_TBL"
TBL_INPUTS = "GXT_INPUTS_TBL"
TBL_INPUT_TYPES = "GXT_INPUTTYPES_TBL"
TBL_TROUBLE_INPUTS = "GXT_TROUBLEINPUTS_TBL"
TBL_OUTPUTS = "GXT_PGMS_TBL"

# Control verbs (Command&Type=Control&SubType=<table>&RecId=<id>&Command=<n>),
# as used by the controller's own web interface.
AREA_DISARM = 0
AREA_ARM_AWAY = 3
AREA_ARM_FORCE = 4
AREA_ARM_INSTANT = 5
AREA_ARM_FORCE_INSTANT = 6
AREA_SILENCE = 9
AREA_ARM_STAY = 10
DOOR_LOCK = 0
DOOR_UNLOCK = 1
DOOR_UNLOCK_LATCHED = 2
INPUT_UNBYPASS = 0
INPUT_BYPASS = 1
INPUT_BYPASS_PERMANENT = 2
OUTPUT_OFF = 0
OUTPUT_ON = 1
OUTPUT_ON_TIMED = 2

ARM_COMMANDS = {
    ("away", False): AREA_ARM_AWAY,
    ("away", True): AREA_ARM_FORCE,
    ("stay", False): AREA_ARM_STAY,
    ("instant", False): AREA_ARM_INSTANT,
    ("instant", True): AREA_ARM_FORCE_INSTANT,
}

MAX_TIMED_SECONDS = 65535
LOGIN_WINDOW = 600.0
MAX_LOGINS_PER_WINDOW = 6
BACKOFF_START = 30.0
BACKOFF_MAX = 600.0
RETRY_DELAY = 0.5

_EMPTY_REPLIES = {"", "FAIL", "<NO RESPONSE>", "REQUEST FAILED"}
_RETRY_REPLY = "command failed (8)"


class ProtegeError(Exception):
    """Base error for the Protege WX client."""


class ProtegeConnectionError(ProtegeError):
    """The controller could not be reached, answered with an HTTP error, or the
    client is backing off to protect it."""


class ProtegeAuthError(ProtegeError):
    """The controller rejected the username or password."""

    def __init__(self, reply: str, lockout_seconds: int | None = None) -> None:
        self.reply = reply
        self.lockout_seconds = lockout_seconds
        message = "login rejected"
        if lockout_seconds:
            message += f"; operator locked out for {lockout_seconds} s"
        super().__init__(message)


class ProtegeSessionError(ProtegeError):
    """The controller no longer recognises the session."""


class ProtegeCommandError(ProtegeError):
    """The controller refused a command."""


def parse_kv(text: str) -> dict[str, str]:
    """Parse a ``key=value&key=value`` reply."""
    out: dict[str, str] = {}
    for part in text.split("&"):
        if "=" in part:
            key, value = part.split("=", 1)
            out[key] = value
    return out


def _numeric(text: str) -> bool:
    text = text.strip()
    return bool(text) and text.lstrip("-").isdigit()


def normalise_host(host: str) -> str:
    """Strip any scheme, path and trailing slash from a host[:port] string."""
    host = host.strip()
    for prefix in ("http://", "https://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix):]
    return host.split("/", 1)[0]


class LoginGuard:
    """Login limits shared by every client for the same controller and
    credentials, so reloads and setup retries can't get round them."""

    def __init__(self, *, known_good: bool = False) -> None:
        # True once these credentials have worked (an existing config entry).
        self.known_good = known_good
        self.login_times: deque[float] = deque()
        self.backoff = 0.0
        self.backoff_until = 0.0
        self.bare_fails = 0


class ProtegeClient:
    """One session to a Protege WX controller."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        *,
        protocol: str = PROTOCOL_AUTO,
        timeout: float = 10.0,
        guard: LoginGuard | None = None,
    ) -> None:
        if protocol not in PROTOCOLS:
            raise ValueError(f"protocol must be one of {PROTOCOLS}")
        self._session = session
        self.host = normalise_host(host)
        self._hostname = URL(f"http://{self.host}").host or self.host
        self.username = username.strip()
        self._password_sha1 = crypto.sha1_hex(password)
        self.protocol = protocol
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._lock = asyncio.Lock()
        self._sessid: str | None = None
        self._key: str | None = None
        self._auth_error: ProtegeAuthError | None = None
        self._closed = False
        self.guard = guard or LoginGuard()

    @property
    def logged_in(self) -> bool:
        return self._key is not None

    @property
    def auth_failed(self) -> bool:
        return self._auth_error is not None

    # ── transport ──────────────────────────────────────────────────────────

    async def _send(self, body: str, protocol: str) -> str:
        if self._session.closed:
            raise ProtegeConnectionError("client session is closed")
        url = f"http://{self.host}/{ENDPOINT}"
        headers = {"Accept": "text/plain, */*"}
        try:
            if protocol == PROTOCOL_LEGACY:
                if self._sessid:
                    headers["Cookie"] = f"SESSID={self._sessid}"
                request = self._session.get(
                    URL(f"{url}?{body}", encoded=True),
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
                headers["X-CSRF-Token"] = ""
                request = self._session.post(
                    url,
                    data=body.encode("latin-1"),
                    headers=headers,
                    timeout=self._timeout,
                )
            async with request as response:
                if response.status >= 400:
                    raise ProtegeConnectionError(f"HTTP {response.status} from {self.host}")
                return (await response.read()).decode("latin-1").strip()
        except (aiohttp.ClientError, TimeoutError, RuntimeError) as err:
            raise ProtegeConnectionError(f"cannot reach {self.host}: {err}") from err

    async def _close_plain(self, protocol: str) -> None:
        """Best-effort unencrypted CloseSession for a half-open session (as the
        web UI does after a failed password check)."""
        with contextlib.suppress(ProtegeError):
            body = "Command&Type=Session&SubType=CloseSession"
            if protocol == PROTOCOL_LEGACY and self._sessid:
                body += f"&SessionID={self._sessid}"
            await self._send(body, protocol)

    # ── login ──────────────────────────────────────────────────────────────

    def _check_login_allowed(self) -> None:
        if self._closed:
            raise ProtegeConnectionError("client is closed")
        if self._auth_error is not None:
            raise self._auth_error
        guard = self.guard
        now = time.monotonic()
        if now < guard.backoff_until:
            raise ProtegeConnectionError(
                f"backing off for {int(guard.backoff_until - now)} s to protect the controller"
            )
        while guard.login_times and now - guard.login_times[0] > LOGIN_WINDOW:
            guard.login_times.popleft()
        if len(guard.login_times) >= MAX_LOGINS_PER_WINDOW:
            self._start_backoff("too many logins in a short time")
            raise ProtegeConnectionError("too many logins in a short time; backing off")
        guard.login_times.append(now)

    def _start_backoff(self, reason: str) -> None:
        guard = self.guard
        guard.backoff = min(BACKOFF_MAX, guard.backoff * 2 if guard.backoff else BACKOFF_START)
        guard.backoff_until = time.monotonic() + guard.backoff
        _LOGGER.warning(
            "Protege WX at %s: %s; pausing logins for %d s", self.host, reason, guard.backoff
        )

    async def _init_session(self, protocol: str) -> int | None:
        """Start a session; return seed0, or None if this protocol isn't spoken."""
        if protocol == PROTOCOL_LEGACY:
            self._sessid = "".join(secrets.choice("0123456789ABCDEF") for _ in range(32))
            reply = await self._send(
                f"Command&Type=Session&SubType=InitSession&SessionID={self._sessid}",
                protocol,
            )
        else:
            self._sessid = None
            self._session.cookie_jar.clear_domain(self._hostname)
            reply = await self._send("Command&Type=Session&SubType=InitSession", protocol)
        return int(reply) if _numeric(reply) else None

    async def _login(self) -> None:
        self._key = None
        self._check_login_allowed()
        order = (PROTOCOL_POST, PROTOCOL_LEGACY) if self.protocol == PROTOCOL_AUTO else (self.protocol,)

        seed0 = None
        protocol = order[0]
        last_error: ProtegeConnectionError | None = None
        for protocol in order:
            try:
                seed0 = await self._init_session(protocol)
            except ProtegeConnectionError as err:
                last_error = err
                continue
            if seed0 is None:
                continue
            if (
                self.protocol == PROTOCOL_AUTO
                and protocol == PROTOCOL_POST
                and not self._has_session_cookie()
            ):
                # 2.3.x always issues a SESSID cookie on InitSession. Older web
                # UIs that happen to accept a POST don't, so use legacy instead.
                _LOGGER.debug("%s gave no session cookie; trying legacy", self.host)
                await self._close_plain(protocol)
                seed0 = None
                continue
            break
        if seed0 is None:
            if last_error is not None:
                raise last_error
            raise ProtegeConnectionError(
                f"{self.host} did not answer InitSession like a Protege WX controller"
            )

        name_hash, password_hash = crypto.login_hashes(self.username, self._password_sha1, seed0)
        check = (
            "Command&Type=Session&SubType=CheckPassword"
            f"&Name={name_hash}&Password={password_hash}"
        )
        if protocol == PROTOCOL_LEGACY:
            check += f"&SessionID={self._sessid}"
        try:
            reply = await self._send(check, protocol)
        except ProtegeConnectionError:
            await self._close_plain(protocol)
            raise
        if reply.upper().startswith("FAIL"):
            await self._close_plain(protocol)
            _, _, tail = reply.partition(":")
            tail = tail.strip()
            if tail.isdigit():
                # "FAIL:<n>" is the controller's verdict on the credentials.
                error = ProtegeAuthError(reply, int(tail) or None)
            elif self.guard.known_good and self.guard.bare_fails == 0:
                # A first bare FAIL with credentials that have worked before
                # may be a full session table rather than a bad password: back
                # off once. A second one in a row (in this or a later client)
                # is treated as a rejected password, so a changed password
                # can't keep counting towards the operator's lockout.
                self.guard.bare_fails += 1
                self._start_backoff("the controller refused a new session")
                raise ProtegeConnectionError("controller refused a new session")
            else:
                error = ProtegeAuthError(reply)
            self._auth_error = error
            raise error
        if not _numeric(reply):
            await self._close_plain(protocol)
            raise ProtegeConnectionError(f"unexpected CheckPassword reply: {reply[:40]!r}")

        self._key = crypto.session_key(self._password_sha1, int(reply))
        if self.protocol == PROTOCOL_AUTO:
            _LOGGER.debug("%s speaks the %s protocol", self.host, protocol)
        self.protocol = protocol
        self.guard.known_good = True
        self.guard.bare_fails = 0
        _LOGGER.debug("Logged in to %s as %s", self.host, self.username)

    def _has_session_cookie(self) -> bool:
        return any(cookie.key == "SESSID" for cookie in self._session.cookie_jar)

    async def login(self) -> None:
        """Log in, detecting the protocol if it is still ``auto``."""
        async with self._lock:
            await self._login()

    async def logout(self) -> None:
        """Close the session on the controller (best effort)."""
        async with self._lock:
            if self._key is not None:
                with contextlib.suppress(ProtegeError):
                    await self._query_once("Command&Type=Session&SubType=CloseSession")
            self._key = None
            self._sessid = None

    async def close(self) -> None:
        """Log out and refuse any further logins (used on unload and shutdown)."""
        await self.logout()
        self._closed = True

    # ── encrypted channel ──────────────────────────────────────────────────

    async def _query_once(self, payload: str) -> str:
        if self._key is None:
            raise ProtegeSessionError("not logged in")
        if self.protocol == PROTOCOL_LEGACY:
            wire = (self._sessid or "") + crypto.encrypt(payload + "&Sequence=", self._key)
        else:
            wire = crypto.encrypt(payload, self._key)
        for attempt in range(3):
            if attempt:
                await asyncio.sleep(RETRY_DELAY)
            reply = await self._send(wire, self.protocol)
            if reply.startswith("<invalid session>"):
                self._key = None
                raise ProtegeSessionError(reply)
            if reply.upper() in _EMPTY_REPLIES:
                return reply
            if reply.lower().startswith(_RETRY_REPLY):
                continue
            try:
                text = crypto.decrypt(reply, self._key)
            except ValueError as err:
                raise ProtegeError(f"undecryptable reply: {reply[:40]!r}") from err
            if text.strip().lower().startswith(_RETRY_REPLY):
                continue
            return text
        raise ProtegeCommandError("controller kept answering 'command failed (8)'")

    async def query(self, payload: str) -> str:
        """Send an encrypted payload and return the decrypted reply.

        Logs in when needed and re-logs in once if the session was dropped. A
        session rejected straight after a fresh login triggers a back-off.
        """
        async with self._lock:
            if self._key is None:
                await self._login()
            try:
                result = await self._query_once(payload)
            except ProtegeSessionError:
                _LOGGER.debug("Session to %s expired; logging in again", self.host)
                await self._login()
                try:
                    result = await self._query_once(payload)
                except ProtegeSessionError as err:
                    self._start_backoff("a brand-new session was rejected straight away")
                    raise ProtegeConnectionError("controller keeps rejecting sessions") from err
            self.guard.backoff = 0.0
            return result

    # ── records ────────────────────────────────────────────────────────────

    async def list_records(self, table: str) -> dict[int, str]:
        """Return {record id: name} for a table."""
        reply = await self.query(f"Request&Type=List&SubType={table}&str=")
        if reply.strip().upper() in _EMPTY_REPLIES:
            return {}
        out: dict[int, str] = {}
        for key, value in parse_kv(reply).items():
            if key.strip().lstrip("-").isdigit():
                out[int(key)] = value
        return out

    async def get_record(self, table: str, rec_id: int) -> dict[str, str]:
        """Return every field of one record (empty if not permitted)."""
        reply = await self.query(f"Request&Type=Detail&SubType={table}&RecId={rec_id}")
        if reply.strip().upper() in _EMPTY_REPLIES:
            return {}
        return parse_kv(reply)

    async def health_values(self) -> dict[str, str]:
        """Return controller health values (serial number, versions, voltage...)."""
        reply = await self.query("Request&Type=Health&SubType=Values")
        return {} if reply.strip().upper() in _EMPTY_REPLIES else parse_kv(reply)

    async def health_troubles(self) -> list[str]:
        """Return the controller's active health troubles (empty when healthy)."""
        reply = await self.query("Request&Type=Health&SubType=List")
        if reply.strip().upper() in _EMPTY_REPLIES:
            return []
        return [value for key, value in parse_kv(reply).items() if value and key != "Sequence"]

    async def events(self, page: str = "Latest") -> list[ProtegeEvent]:
        """Return one page of the controller's event log, oldest first.

        ``page`` is ``Latest`` (newest batch), ``Previous`` (the page before the
        last one read in this session) or ``Update`` (new since the last read).
        """
        reply = await self.query(f"Request&Type=Events&SubType={page}")
        if reply.strip().upper() in _EMPTY_REPLIES:
            return []
        return parse_event_reply(reply)

    # ── live status ────────────────────────────────────────────────────────

    async def _status(self, table: str) -> str:
        reply = await self.query(f"Request&Type=Status&SubType={table}")
        return "" if reply.strip().upper() in _EMPTY_REPLIES else reply

    async def area_status(self) -> dict[int, AreaStatus]:
        return parse_areas(await self._status(TBL_AREAS))

    async def door_status(self) -> dict[int, DoorStatus]:
        return parse_doors(await self._status(TBL_DOORS))

    async def input_status(self) -> dict[int, InputStatus]:
        return parse_inputs(await self._status(TBL_INPUTS))

    async def trouble_input_status(self) -> dict[int, InputStatus]:
        return parse_inputs(await self._status(TBL_TROUBLE_INPUTS))

    async def output_status(self) -> dict[int, OutputStatus]:
        return parse_outputs(await self._status(TBL_OUTPUTS))

    # ── control ────────────────────────────────────────────────────────────

    async def control(
        self, table: str, rec_id: int, command: int, data1: int | None = None
    ) -> None:
        """Send a control verb; raise ProtegeCommandError unless the reply is OK."""
        payload = f"Command&Type=Control&SubType={table}&RecId={rec_id}&Command={command}"
        if data1 is not None:
            payload += f"&Data1={data1}"
        reply = await self.query(payload)
        if reply.strip() != "OK":
            raise ProtegeCommandError(f"{table} {rec_id} command {command} refused: {reply!r}")

    async def arm_area(self, area_id: int, mode: str = "away", *, force: bool = False) -> None:
        try:
            command = ARM_COMMANDS[(mode, force)]
        except KeyError as err:
            raise ValueError(f"cannot arm in mode {mode!r} with force={force}") from err
        await self.control(TBL_AREAS, area_id, command)

    async def disarm_area(self, area_id: int) -> None:
        await self.control(TBL_AREAS, area_id, AREA_DISARM)

    async def silence_area(self, area_id: int) -> None:
        await self.control(TBL_AREAS, area_id, AREA_SILENCE)

    async def lock_door(self, door_id: int) -> None:
        await self.control(TBL_DOORS, door_id, DOOR_LOCK)

    async def unlock_door(self, door_id: int, *, latched: bool = False) -> None:
        await self.control(TBL_DOORS, door_id, DOOR_UNLOCK_LATCHED if latched else DOOR_UNLOCK)

    async def set_bypass(self, input_id: int, mode: str) -> None:
        command = {
            "none": INPUT_UNBYPASS,
            "temporary": INPUT_BYPASS,
            "permanent": INPUT_BYPASS_PERMANENT,
        }[mode]
        await self.control(TBL_INPUTS, input_id, command)

    async def set_output(self, output_id: int, on: bool, seconds: int | None = None) -> None:
        if on and seconds:
            seconds = max(1, min(int(seconds), MAX_TIMED_SECONDS))
            await self.control(TBL_OUTPUTS, output_id, OUTPUT_ON_TIMED, seconds)
        else:
            await self.control(TBL_OUTPUTS, output_id, OUTPUT_ON if on else OUTPUT_OFF)

