"""Enable DRY + FAN_ONLY HVAC modes for Matter A/Cs that Home Assistant doesn't allowlist.

Home Assistant's Matter climate integration only exposes the Dry and Fan-only HVAC modes for
`(vendor_id, product_id)` pairs hardcoded in `SUPPORT_DRY_MODE_DEVICES` /
`SUPPORT_FAN_MODE_DEVICES` (the Matter thermostat cluster has no feature flag for those modes,
so HA maintains a device list). Devices using the Matter *test* vendor `0xFFF1` -- e.g.
DIY / ESP32 / esp-matter A/C bridges -- are never on that list, so Dry/Fan never show up even
though the firmware maps them correctly. See home-assistant/core#135124.

This tiny integration adds your `(vendor_id, product_id)` to both lists at startup and reloads
the Matter config entry so the modes appear. Unlike editing HA's core `climate.py`, it lives in
`custom_components/` and therefore **survives Home Assistant upgrades**. It is wrapped in
try/except so an internal HA refactor can never break your boot.

Default targets the common test IDs `(0xFFF1, 0x8000)`. Override / extend via configuration.yaml:

    matter_extra_hvac_modes:
      devices:
        - [0xFFF1, 0x8000]
        - [0xFFF1, 0x8001]
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

DOMAIN = "matter_extra_hvac_modes"
CONF_DEVICES = "devices"

# Sensible default: the Matter test vendor + the usual first test product id.
DEFAULT_DEVICES: list[tuple[int, int]] = [(0xFFF1, 0x8000)]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_DEVICES): [
                    vol.All([vol.Coerce(int)], vol.Length(min=2, max=2))
                ]
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Patch the Matter climate Dry/Fan allowlists (idempotent)."""
    conf = config.get(DOMAIN) or {}
    devices: set[tuple[int, int]] = set(DEFAULT_DEVICES)
    for pair in conf.get(CONF_DEVICES, []):
        devices.add((int(pair[0]), int(pair[1])))

    try:
        # Imported lazily so the integration loads even if HA's Matter component isn't set up.
        from homeassistant.components.matter import climate as matter_climate

        for dev in devices:
            matter_climate.SUPPORT_DRY_MODE_DEVICES.add(dev)
            matter_climate.SUPPORT_FAN_MODE_DEVICES.add(dev)

        _LOGGER.info(
            "Enabled Matter Dry/Fan-only HVAC modes for %s",
            ", ".join(f"(0x{v:04X}, 0x{p:04X})" for v, p in sorted(devices)),
        )

        # Recompute features on any already-created climate entities so the modes appear
        # without a full restart (the allowlists are read live in _calculate_features()).
        for entry in hass.config_entries.async_entries("matter"):
            hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
    except Exception:  # noqa: BLE001 - never let an HA-internals change break boot
        _LOGGER.exception(
            "Failed to patch the Matter climate Dry/Fan allowlists "
            "(HA internals may have changed); Dry/Fan modes will not be added"
        )

    return True
