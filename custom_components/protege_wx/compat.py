"""Compatibility with older Home Assistant releases."""
from __future__ import annotations

try:  # Home Assistant 2025.3 and later
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:  # pragma: no cover - older releases
    from homeassistant.helpers.entity_platform import (  # type: ignore[assignment]
        AddEntitiesCallback as AddConfigEntryEntitiesCallback,
    )

__all__ = ["AddConfigEntryEntitiesCallback"]
