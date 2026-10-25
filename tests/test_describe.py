"""Plain-English logbook descriptions."""
from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.protege_wx.describe import describe, join_names
from custom_components.protege_wx.wxapi.events import EventParser, ProtegeEvent

PARSER = EventParser(
    ["Alarm"], ["Front Door", "Gate"], ["Living", "Kitchen"], ["Analog Expander 1 Mains Failure"]
)


def _describe(text: str, **kwargs):
    return describe(PARSER.parse(ProtegeEvent(datetime(2026, 10, 26, 9, 0), text)), **kwargs)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Area Alarm Stay Armed By Home Assistant", ("Alarm", "armed (home) by Home Assistant")),
        ("Area Alarm Armed By User Jane Citizen", ("Alarm", "armed (away) by Jane Citizen")),
        ("Area Alarm Instant Armed By Home Assistant", ("Alarm", "armed (night) by Home Assistant")),
        ("Area Alarm Stay Arming Started By Home Assistant", ("Alarm", "started arming (home) by Home Assistant")),
        ("Area Alarm Arming Cancelled By Home Assistant", ("Alarm", "arming cancelled by Home Assistant")),
        ("Area Alarm Disarmed By User Jane Citizen", ("Alarm", "disarmed by Jane Citizen")),
        ("User Jane Citizen Entry Granted Front Door Using User By Pin", ("Front Door", "access granted to Jane Citizen (PIN)")),
        ("User Jane Citizen Entry Denied Front Door Using Card", ("Front Door", "access denied to Jane Citizen (card)")),
        ("Door Gate Unlocked By Door Front Door", ("Gate", "unlocked by Front Door")),
        ("Door Front Door Forced Open", ("Front Door", "was forced open")),
        ("Trouble Input Analog Expander 1 Mains Failure Opened", ("Analog Expander 1 Mains Failure", "trouble started")),
        ("Trouble Input Analog Expander 1 Mains Failure Closed", ("Analog Expander 1 Mains Failure", "trouble cleared")),
        ("System Power Up", ("Protege WX", "powered up")),
    ],
)
def test_sentences(text, expected):
    assert _describe(text) == expected


def test_failed_to_arm_names_zones():
    text = "Area Alarm Failure To ARM By Home Assistant"
    assert _describe(text, zones=["Living", "Kitchen"]) == (
        "Alarm", "failed to arm by Home Assistant: Living and Kitchen are open"
    )
    assert _describe(text, zones=["Living"])[1].endswith("Living is open")
    assert _describe(text, zones=[]) == ("Alarm", "failed to arm by Home Assistant")


def test_who_can_be_overridden():
    text = "Area Alarm Disarmed By Home Assistant"
    assert _describe(text, by="Oliver (Home Assistant)") == ("Alarm", "disarmed by Oliver (Home Assistant)")


def test_zone_events_are_left_to_their_sensors():
    assert _describe("Input Living Opened") is None


def test_join_names():
    assert join_names([]) == ""
    assert join_names(["A"]) == "A"
    assert join_names(["A", "B", "C"]) == "A, B and C"
