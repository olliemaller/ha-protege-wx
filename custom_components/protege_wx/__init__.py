"""The ICT Protege WX integration.

Talks to a Protege WX controller through its built-in web-programming
interface, so no Automation & Integration licence is needed.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .alarmo import AlarmoSync
from .card import async_register_card
from .const import (
    CONF_PROTOCOL,
    DOMAIN,
    INTEGRATION_AUTHOR,
    OPT_ALARMO_AREA,
    OPT_ALARMO_ENTITY,
)
from .coordinator import ProtegeCoordinator, ProtegeSite, async_discover
from .entity import controller_device, controller_uid, object_identifier
from .health import entry_health
from .visitor import VisitorUnlocks, visitor_store
from .voice import async_setup_voice
from .wxapi import (
    PROTOCOL_AUTO,
    LoginGuard,
    ProtegeAuthError,
    ProtegeClient,
    ProtegeError,
)
from .wxapi.crypto import sha1_hex

if TYPE_CHECKING:
    from .alarm_control_panel import ProtegeArea

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
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
    areas: dict[int, ProtegeArea] = field(default_factory=dict)


type ProtegeConfigEntry = ConfigEntry[ProtegeRuntimeData]


def create_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    """A private session owned and closed by this integration.

    The controller's session cookie must not leak into Home Assistant's shared
    session, and it is set on a bare IP address, which needs an ``unsafe``
    cookie jar. The controller only speaks plain HTTP on the LAN.
    """
    return aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))


async def async_setup_entry(hass: HomeAssistant, entry: ProtegeConfigEntry) -> bool:
    """Set up a Protege WX controller from a config entry."""
    # One login guard per entry and password, kept across reloads and setup
    # retries so they can't get round the login limits. These credentials
    # worked when the entry was created, hence known_good.
    guards: dict = hass.data.setdefault(DOMAIN, {})
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
        await client.close()
        await session.close()

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
        raise ConfigEntryAuthFailed(str(err)) from err
    except ProtegeError as err:
        await _close()
        # Counts towards the "unreachable" Repair even across setup retries.
        entry_health(hass, entry.entry_id).record_failure(client.host)
        raise ConfigEntryNotReady(f"Cannot set up the controller: {err}") from err
    except BaseException:
        await _close()
        raise

    visitors = VisitorUnlocks(hass, coordinator)
    await visitors.async_start()
    entry.runtime_data = ProtegeRuntimeData(client, coordinator, site, visitors)
    entry.async_on_unload(visitors.async_stop)
    entry.async_on_unload(_close)
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _close))
    if not _HAS_RELOADING_OPTIONS_FLOW:
        entry.async_on_unload(entry.add_update_listener(_async_reload_on_options))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(async_setup_voice(hass))
    await async_register_card(hass)
    if entry.options.get(OPT_ALARMO_ENTITY) and entry.options.get(OPT_ALARMO_AREA) is not None:
        sync = AlarmoSync(hass, entry)
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
    else:
        parent = {"via_device": next(iter(controller.identifiers))}
    site = coordinator.site
    for kind, model, objects in (
        ("area", "Protege WX area", site.areas.values()),
        ("door", "Protege WX door", site.doors.values()),
        ("input", "Protege WX input", site.inputs.values()),
    ):
        for obj in objects:
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={object_identifier(coordinator, kind, obj.id)},
                name=obj.name,
                manufacturer=INTEGRATION_AUTHOR,
                model=model,
                **parent,
            )


async def _async_reload_on_options(hass: HomeAssistant, entry: ProtegeConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ProtegeConfigEntry) -> bool:
    """Unload a config entry; the session is logged out by the unload hooks."""
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
    for kind, ids in (("area", site.areas), ("door", site.doors), ("input", site.inputs)):
        current |= {object_identifier(coordinator, kind, rec_id) for rec_id in ids}
    return not (device.identifiers & current)


async def async_remove_entry(hass: HomeAssistant, entry: ProtegeConfigEntry) -> None:
    """Delete what's stored for the entry (people's last-seen history)."""
    from homeassistant.helpers.storage import Store

    hass.data.get(DOMAIN, {}).pop(("people", entry.entry_id), None)
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.people").async_remove()
    await visitor_store(hass, entry.entry_id).async_remove()
    from homeassistant.helpers import issue_registry as ir

    from .const import ISSUE_EMERGENCY

    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_EMERGENCY}_{entry.entry_id}")
