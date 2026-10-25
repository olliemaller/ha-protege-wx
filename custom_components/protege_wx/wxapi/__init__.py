"""Minimal async client for the ICT Protege WX web-programming protocol.

Bundled with the Home Assistant integration so it needs no extra packages.
Protocol work derived from protege-wx-cli by Mitchell Johnson (MIT licence),
extended for web UI 2.3.x controllers.
"""
from .client import (
    PROTOCOL_AUTO,
    PROTOCOL_LEGACY,
    PROTOCOL_POST,
    TBL_AREAS,
    TBL_DOORS,
    TBL_INPUT_TYPES,
    TBL_INPUTS,
    TBL_OUTPUTS,
    TBL_TROUBLE_INPUTS,
    LoginGuard,
    ProtegeAuthError,
    ProtegeClient,
    ProtegeCommandError,
    ProtegeConnectionError,
    ProtegeError,
    ProtegeSessionError,
    normalise_host,
)
from .events import EventParser, ParsedEvent, ProtegeEvent
from .status import NO_RECORD, AreaStatus, DoorStatus, InputStatus, OutputStatus

__all__ = [
    "NO_RECORD",
    "PROTOCOL_AUTO",
    "PROTOCOL_LEGACY",
    "PROTOCOL_POST",
    "TBL_AREAS",
    "TBL_DOORS",
    "TBL_INPUTS",
    "TBL_INPUT_TYPES",
    "TBL_OUTPUTS",
    "TBL_TROUBLE_INPUTS",
    "AreaStatus",
    "DoorStatus",
    "EventParser",
    "InputStatus",
    "LoginGuard",
    "OutputStatus",
    "ParsedEvent",
    "ProtegeAuthError",
    "ProtegeClient",
    "ProtegeCommandError",
    "ProtegeConnectionError",
    "ProtegeError",
    "ProtegeEvent",
    "ProtegeSessionError",
    "normalise_host",
]
