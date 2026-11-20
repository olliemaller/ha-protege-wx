"""Compatibility with older Home Assistant releases."""
from __future__ import annotations

try:  # Home Assistant 2025.3 and later
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:  # pragma: no cover - older releases
    from homeassistant.helpers.entity_platform import (  # type: ignore[assignment]
        AddEntitiesCallback as AddConfigEntryEntitiesCallback,
    )

try:  # Home Assistant 2026.10 moved its schemas to probatio.
    import probatio as vol
except ImportError:  # pragma: no cover - older Home Assistant
    import voluptuous as vol  # type: ignore[no-redef]

__all__ = ["AddConfigEntryEntitiesCallback", "vol"]
