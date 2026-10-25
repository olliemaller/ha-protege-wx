"""Base entity for the ICT Protege WX integration."""
from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import ProtegeCoordinator
from .wxapi import ProtegeAuthError, ProtegeError


def controller_uid(coordinator: ProtegeCoordinator) -> str:
    """Stable identifier for the controller.

    The config entry's unique ID is the serial number when it could be read at
    setup; otherwise the entry ID is used permanently, so identifiers never
    switch if the operator's permissions change later.
    """
    entry = coordinator.config_entry
    return entry.unique_id or entry.entry_id


def object_identifier(coordinator: ProtegeCoordinator, kind: str, rec_id: int) -> tuple[str, str]:
    """Device-registry identifier of an area, door or input."""
    return (DOMAIN, f"{controller_uid(coordinator)}_{kind}_{rec_id}")


def controller_device(coordinator: ProtegeCoordinator) -> DeviceInfo:
    site = coordinator.site
    return DeviceInfo(
        identifiers={(DOMAIN, controller_uid(coordinator))},
        name="Protege WX controller",
        manufacturer=MANUFACTURER,
        model=site.model,
        serial_number=site.serial,
        sw_version=site.firmware,
        configuration_url=f"http://{coordinator.client.host}",
    )


class ProtegeEntity(CoordinatorEntity[ProtegeCoordinator]):
    """An entity attached to the controller or to one area, door or input."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ProtegeCoordinator,
        kind: str,
        rec_id: int,
        *,
        key: str | None = None,
        own_device: bool = False,
    ) -> None:
        super().__init__(coordinator)
        self.rec_id = rec_id
        uid = controller_uid(coordinator)
        self._attr_unique_id = f"{uid}_{kind}_{rec_id}" + (f"_{key}" if key else "")
        if own_device:
            # The device itself is registered at setup (linked to the
            # controller); here we only point at it.
            self._attr_device_info = DeviceInfo(
                identifiers={object_identifier(coordinator, kind, rec_id)}
            )
        else:
            self._attr_device_info = controller_device(coordinator)

    async def _send(self, action: Awaitable[None]) -> None:
        """Run a control command, translating failures for the user."""
        try:
            await action
        except ProtegeAuthError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except ProtegeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _command(self, action: Awaitable[None]) -> None:
        """Run a control command, then re-read status straight away."""
        await self._send(action)
        await self.coordinator.async_refresh_all()
