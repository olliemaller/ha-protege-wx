"""Constants for the ICT Protege WX integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "protege_wx"
MANUFACTURER: Final = "Integrated Control Technology"
# Areas, doors and inputs are devices this integration creates, not ICT hardware.
INTEGRATION_AUTHOR: Final = "Arcnode IT"

CONF_PROTOCOL: Final = "protocol"
CONF_SERIAL: Final = "serial"

# Options
OPT_SCAN_INTERVAL: Final = "scan_interval"  # fast loop, seconds
OPT_SHOW_ARMING: Final = "show_arming"
OPT_OUTPUTS: Final = "outputs"
OPT_INPUT_TYPES: Final = "input_types"
OPT_USERS: Final = "users"
OPT_CODE_ARM_REQUIRED: Final = "code_arm_required"
OPT_NOTIFY_FAILED_ARM: Final = "notify_failed_arm"
OPT_PANEL_CODE: Final = "panel_code"  # v0.1 single code, migrated to OPT_USERS

# User records in OPT_USERS
USER_NAME: Final = "name"
USER_CODE_HASH: Final = "code_hash"
USER_SALT: Final = "salt"
USER_CAN_ARM: Final = "can_arm"
USER_CAN_DISARM: Final = "can_disarm"

DEFAULT_SCAN_INTERVAL: Final = 1
MIN_SCAN_INTERVAL: Final = 1
MAX_SCAN_INTERVAL: Final = 30
FULL_REFRESH_SECONDS: Final = 5.0
HEALTH_REFRESH_SECONDS: Final = 60.0
EVENT_HISTORY: Final = 50

# Bus events
EVENT_FAILED_TO_ARM: Final = "protege_wx_failed_to_arm"
EVENT_LOG: Final = "protege_wx_event"
# Logbook-only: carries a ready-made sentence; not meant for automations.
EVENT_LOGBOOK: Final = "protege_wx_logbook"

# Repairs
UNREACHABLE_ISSUE_SECONDS: Final = 15 * 60
LOW_VOLTAGE: Final = 12.0  # volts: raise the issue below this...
LOW_VOLTAGE_CLEAR: Final = 12.5  # ...and clear it at or above this
LOW_VOLTAGE_SECONDS: Final = 5 * 60
EVENT_LOG_EMPTY_SECONDS: Final = 5 * 60
ISSUE_UNREACHABLE: Final = "controller_unreachable"
ISSUE_LOW_VOLTAGE: Final = "low_supply_voltage"
ISSUE_EVENT_LOG: Final = "event_log_unreadable"

DEFAULT_INPUT_TYPE: Final = "motion"
INPUT_TYPES: Final = (
    "motion",
    "occupancy",
    "door",
    "window",
    "garage_door",
    "opening",
    "vibration",
    "smoke",
    "gas",
    "moisture",
    "safety",
)
