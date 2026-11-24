"""The ICT Protege WX integration.

Talks to a Protege WX controller through its built-in web-programming
interface over plain HTTP, so no Automation and Control licence is needed.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

import aiohttp
from aioprotegewx import (
    PROTOCOL_AUTO,
    LoginGuard,
    ProtegeAuthError,
    ProtegeClient,
    ProtegeError,
)
from aioprotegewx.client import MAX_TIMED_SECONDS
from aioprotegewx.crypto import sha1_hex
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import async_get_platforms
from homeassistant.helpers.service import entity_service_call
from homeassistant.helpers.typing import ConfigType

from .alarmo import AlarmoSync
from .arm_when_ready import MODES as WAIT_MODES
from .arm_when_ready import ArmWhenReady
from .card import async_register_card
from .compat import async_extract_entities, vol
from .const import (
    ARM_MODES,
    BYPASS_MODES,
    CONF_PROTOCOL,
    DOMAIN,
    MANUFACTURER,
    OPT_ALARMO_AREA,
    OPT_ALARMO_ENTITY,
    OPT_OUTPUTS,
)
from .coordinator import ProtegeCoordinator, ProtegeSite, async_discover
from .entity import controller_device, controller_uid, object_identifier
from .health import entry_health
from .visitor import VisitorUnlocks, async_hand_over_visitors
from .voice import async_setup_voice

if TYPE_CHECKING:
    from .alarm_control_panel import ProtegeArea

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.LOCK,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class ProtegeRuntimeData:
    """Objects shared by the platforms of one config entry."""

    client: ProtegeClient
    coordinator: ProtegeCoordinator
    site: ProtegeSite
    visitors: VisitorUnlocks | None = None
    alarmo: AlarmoSync | None = None
    arm_when_ready: ArmWhenReady | None = None
    areas: dict[int, ProtegeArea] = field(default_factory=dict)


type ProtegeConfigEntry = ConfigEntry[ProtegeRuntimeData]


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_MINUTES = vol.All(vol.Coerce(int), vol.Range(min=1, max=240))
# Action -> (entity domain it targets, entity method, fields).
_ACTIONS: dict[str, tuple[str, str, dict[Any, Any]]] = {
    "arm": (
        Platform.ALARM_CONTROL_PANEL,
        "async_service_arm",
        {
            vol.Required("mode"): vol.In(ARM_MODES),
            vol.Optional("force", default=False): cv.boolean,
            vol.Optional("code"): cv.string,
        },
    ),
    "arm_when_ready": (
        Platform.ALARM_CONTROL_PANEL,
        "async_service_arm_when_ready",
        {
            vol.Optional("mode", default="away"): vol.In(WAIT_MODES),
            vol.Optional("minutes"): _MINUTES,
            vol.Optional("code"): cv.string,
        },
    ),
    "set_user_enabled": (
        Platform.ALARM_CONTROL_PANEL,
        "async_service_set_user_enabled",
        {vol.Required("user"): cv.string, vol.Required("enabled"): cv.boolean},
    ),
    "unlock_door": (
        Platform.LOCK,
        "async_service_unlock",
        {vol.Optional("hold_open", default=False): cv.boolean, vol.Optional("code"): cv.string},
    ),
    "visitor_unlock": (
        Platform.LOCK,
        "async_visitor_unlock",
        {vol.Optional("minutes"): _MINUTES, vol.Optional("code"): cv.string},
    ),
    "bypass": (
        Platform.BINARY_SENSOR,
        "async_service_bypass",
        {vol.Required("mode"): vol.In(BYPASS_MODES), vol.Optional("code"): cv.string},
    ),
    "pulse_output": (
        Platform.SWITCH,
        "async_service_pulse",
        {vol.Required("seconds"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_TIMED_SECONDS))},
    ),
}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions once, so they exist even before an entry loads."""
    for name, (entity_domain, method, fields) in _ACTIONS.items():
        hass.services.async_register(
            DOMAIN,
            name,
            partial(_async_handle_action, hass, entity_domain, method),
            schema=cv.make_entity_service_schema(fields),
        )
    return True


async def _async_handle_action(
    hass: HomeAssistant, entity_domain: str, method: str, call: ServiceCall
) -> None:
    """Run an action on the targeted entities of loaded entries."""
    entities: dict[str, Entity] = {
        entity_id: entity
        for platform in async_get_platforms(hass, DOMAIN)
        if platform.domain == entity_domain
        and platform.config_entry is not None
        and platform.config_entry.state is ConfigEntryState.LOADED
        for entity_id, entity in platform.entities.items()
    }
    if not await async_extract_entities(hass, entities.values(), call):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_loaded",
            translation_placeholders={"action": f"{DOMAIN}.{call.service}"},
        )
    await entity_service_call(hass, entities, method, call)


def create_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    """A session of this integration's own, on Home Assistant's connection pool.

    The controller's session cookie must not leak into Home Assistant's shared
    session, and it is set on a bare IP address, which needs an ``unsafe``
    cookie jar. The controller only speaks plain HTTP on the LAN. Home
    Assistant detaches the session on unload or shutdown, so it isn't closed
    here.
    """
    return async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar(unsafe=True))


async def async_setup_entry(hass: HomeAssistant, entry: ProtegeConfigEntry) -> bool:
    """Set up a Protege WX controller from a config entry."""
    # One login guard per entry and password, kept across reloads and setup
    # retries so they can't get round the login limits. These credentials
    # worked when the entry was created, hence known_good.
    guards: dict[Any, Any] = hass.data.setdefault(DOMAIN, {})
    guard_key = (entry.entry_id, sha1_hex(entry.data[CONF_PASSWORD]))
    for key in [k for k in guards if k[0] == entry.entry_id and k != guard_key]:
        guards.pop(key)  # the password changed: start afresh
    guard = guards.setdefault(guard_key, LoginGuard(known_good=True))

    session = create_session(hass)
    client = ProtegeClient(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        protocol=entry.data.get(CONF_PROTOCOL, PROTOCOL_AUTO),
        guard=guard,
    )

    async def _close(_event: Event | None = None) -> None:
        # Logs out. Home Assistant detaches the session itself on unload.
        await client.close()

    try:
        await client.login()
        site = await async_discover(client)
        if client.protocol != entry.data.get(CONF_PROTOCOL):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_PROTOCOL: client.protocol}
            )
        coordinator = ProtegeCoordinator(hass, entry, client, site)
        _register_devices(hass, entry, coordinator)
        await coordinator.async_config_entry_first_refresh()
    except ProtegeAuthError as err:
        await _close()
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="setup_auth_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    except ProtegeError as err:
        await _close()
        # Counts towards the "unreachable" Repair even across setup retries.
        entry_health(hass, entry.entry_id).record_failure(client.host)
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="setup_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    except BaseException:
        await _close()
        raise

    visitors = VisitorUnlocks(hass, coordinator)
    await visitors.async_start()
    waits = ArmWhenReady(hass, coordinator)
    entry.runtime_data = ProtegeRuntimeData(
        client, coordinator, site, visitors, arm_when_ready=waits
    )
    waits.async_start()
    entry.async_on_unload(waits.async_stop)
    entry.async_on_unload(visitors.async_stop)
    entry.async_on_unload(_close)
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _close))
    if not _HAS_RELOADING_OPTIONS_FLOW:  # pragma: no cover - Home Assistant before 2025.8
        entry.async_on_unload(entry.add_update_listener(_async_reload_on_options))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(async_setup_voice(hass))
    await async_register_card(hass)
    if entry.options.get(OPT_ALARMO_ENTITY) and entry.options.get(OPT_ALARMO_AREA) is not None:
        sync = AlarmoSync(hass, entry)
        entry.runtime_data.alarmo = sync
        sync.async_start()
        entry.async_on_unload(sync.async_stop)
    return True


try:  # Home Assistant 2025.8+ reloads the entry itself after an options change.
    from homeassistant.config_entries import OptionsFlowWithReload  # noqa: F401

    _HAS_RELOADING_OPTIONS_FLOW = True
except ImportError:  # pragma: no cover - older Home Assistant
    _HAS_RELOADING_OPTIONS_FLOW = False

# Home Assistant 2026.10 added via_device_id and deprecated via_device;
# older versions only accept via_device.
_SUPPORTS_VIA_DEVICE_ID = (
    "via_device_id" in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters
)


def _register_devices(
    hass: HomeAssistant, entry: ProtegeConfigEntry, coordinator: ProtegeCoordinator
) -> None:
    """Create the controller device and one child device per area, door and input."""
    registry = dr.async_get(hass)
    controller = registry.async_get_or_create(
        config_entry_id=entry.entry_id, **controller_device(coordinator)
    )
    if _SUPPORTS_VIA_DEVICE_ID:
        parent: dict[str, Any] = {"via_device_id": controller.id}
    else:  # pragma: no cover - Home Assistant before 2026.10
        parent = {"via_device": next(iter(controller.identifiers))}
    site = coordinator.site
    chosen_outputs = {int(rec_id) for rec_id in entry.options.get(OPT_OUTPUTS, [])}
    named: list[tuple[str, str, list[tuple[int, str]]]] = [
        ("area", "Protege WX area", [(a.id, a.name) for a in site.areas.values()]),
        ("door", "Protege WX door", [(d.id, d.name) for d in site.doors.values()]),
        ("input", "Protege WX input", [(i.id, i.name) for i in site.inputs.values()]),
        (
            "output",
            "Protege WX output",
            [(rec_id, name) for rec_id, name in site.outputs.items() if rec_id in chosen_outputs],
        ),
    ]
    for kind, model, objects in named:
        for rec_id, name in objects:
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={object_identifier(coordinator, kind, rec_id)},
                name=name,
                manufacturer=MANUFACTURER,
                model=model,
                **parent,
            )


async def _async_reload_on_options(hass: HomeAssistant, entry: ProtegeConfigEntry) -> None:  # pragma: no cover
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ProtegeConfigEntry) -> bool:
    """Unload a config entry; the session is logged out by the unload hooks."""
    # Stop "arm when ready" first, so nothing arms while the panels go away.
    if entry.runtime_data.arm_when_ready is not None:
        entry.runtime_data.arm_when_ready.async_stop()
    # Nothing re-locks a visitor door while the entry is unloaded (or after
    # it's removed), so lock now. A door that won't lock stays saved for the
    # next setup.
    if entry.runtime_data.visitors is not None:
        await entry.runtime_data.visitors.async_relock_all()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.coordinator.async_clear_issues()
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ProtegeConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing devices for areas, doors or inputs no longer on the controller."""
    coordinator = entry.runtime_data.coordinator
    site = coordinator.site
    current = {(DOMAIN, controller_uid(coordinator))}
    chosen_outputs = {int(rec_id) for rec_id in entry.options.get(OPT_OUTPUTS, [])}
    outputs = [rec_id for rec_id in site.outputs if rec_id in chosen_outputs]
    for kind, ids in (
        ("area", site.areas),
        ("door", site.doors),
        ("input", site.inputs),
        ("output", outputs),
    ):
        current |= {object_identifier(coordinator, kind, rec_id) for rec_id in ids}
    return not (device.identifiers & current)


async def async_remove_entry(hass: HomeAssistant, entry: ProtegeConfigEntry) -> None:
    """Delete what's stored for the entry: people's last-seen history, and
    the login guards, PIN guard and health tracker kept across reloads."""
    from homeassistant.helpers.storage import Store

    data: dict[Any, Any] = hass.data.get(DOMAIN, {})
    for key in [k for k in data if isinstance(k, tuple) and entry.entry_id in k]:
        data.pop(key)
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.people").async_remove()
    await async_hand_over_visitors(hass, entry)
    from homeassistant.helpers import issue_registry as ir

    from .const import ISSUE_EMERGENCY

    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_EMERGENCY}_{entry.entry_id}")
