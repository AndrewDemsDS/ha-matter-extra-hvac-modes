"""Enable DRY + FAN_ONLY HVAC modes for Matter A/Cs that Home Assistant doesn't allowlist.

Home Assistant's Matter climate integration only exposes the Dry and Fan-only HVAC modes for
`(vendor_id, product_id)` pairs hardcoded in `SUPPORT_DRY_MODE_DEVICES` /
`SUPPORT_FAN_MODE_DEVICES` (the Matter Thermostat cluster has no feature flag for those modes,
so HA maintains a device list). Devices using the Matter *test* vendor `0xFFF1` -- e.g.
DIY / ESP32 / esp-matter A/C bridges -- are never on that list, so Dry/Fan never appear even
though the firmware maps them correctly. See home-assistant/core#135124.

This integration makes those modes appear **automatically**. By default it enables Dry/Fan for
*every* Matter climate entity whose **vendor id is `0xFFF1`** (the Matter test vendor used by
almost all DIY/ESP32 builds) -- so you don't have to list each device's product id. You can add
other vendors, or list explicit `(vendor_id, product_id)` pairs for non-test-vendor devices.

Unlike editing HA's core `climate.py` (wiped on every upgrade), this lives in
`custom_components/` and **survives upgrades**, and it's wrapped in try/except so an internal HA
refactor can never break your boot.

Configuration (all optional):

    matter_extra_hvac_modes:
      vendors: [0xFFF1]          # every product of these vendors gets Dry+Fan (default: [0xFFF1])
      devices:                   # explicit (vendor_id, product_id) pairs, for non-test vendors
        - [0x1234, 0x5678]
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

DOMAIN = "matter_extra_hvac_modes"
CONF_VENDORS = "vendors"
CONF_DEVICES = "devices"

# The Matter "test" vendor id -- used by virtually every DIY / ESP32 / esp-matter build. Every
# A/C on this vendor gets Dry + Fan-only automatically (no need to know its product id).
DEFAULT_VENDORS: list[int] = [0xFFF1]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_VENDORS): [vol.Coerce(int)],
                vol.Optional(CONF_DEVICES): [
                    vol.All([vol.Coerce(int)], vol.Length(min=2, max=2))
                ],
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


class _MatchSet:
    """A drop-in replacement for HA's allowlist `set` that also matches by vendor.

    Membership is True when the `(vendor_id, product_id)` pair is:
      * in the original HA allowlist (so built-in devices keep working), OR
      * explicitly configured, OR
      * from a configured vendor id (the "automatic" case -- any product of that vendor).
    Behaves enough like a set (``in``, ``add``, iteration) for HA's usage.
    """

    def __init__(
        self, wrapped: set, vendors: set[int], pairs: set[tuple[int, int]]
    ) -> None:
        self._wrapped = wrapped
        self._vendors = vendors
        self._pairs = pairs

    def __contains__(self, item: object) -> bool:
        try:
            vendor_id = item[0]  # type: ignore[index]
        except (TypeError, IndexError):
            return item in self._wrapped
        return (
            vendor_id in self._vendors or item in self._pairs or item in self._wrapped
        )

    def add(self, item: tuple[int, int]) -> None:
        self._pairs.add(item)

    def __iter__(self):
        return iter(self._wrapped | self._pairs)

    def __repr__(self) -> str:  # for logs / debugging
        return f"_MatchSet(vendors={self._vendors}, extra={self._pairs}, base={self._wrapped})"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Make the Matter climate Dry/Fan allowlists vendor-aware (idempotent)."""
    conf = config.get(DOMAIN) or {}
    vendors = {int(v) for v in conf.get(CONF_VENDORS, DEFAULT_VENDORS)}
    pairs = {(int(p[0]), int(p[1])) for p in conf.get(CONF_DEVICES, [])}

    try:
        # Imported lazily so this loads even if HA's Matter component isn't set up yet.
        from homeassistant.components.matter import climate as matter_climate

        # Wrap the originals unless we've already wrapped them (reloads / repeated setup).
        dry = matter_climate.SUPPORT_DRY_MODE_DEVICES
        fan = matter_climate.SUPPORT_FAN_MODE_DEVICES
        if not isinstance(dry, _MatchSet):
            matter_climate.SUPPORT_DRY_MODE_DEVICES = _MatchSet(
                dry, vendors, set(pairs)
            )
        else:
            dry._vendors |= vendors
            dry._pairs |= pairs
        if not isinstance(fan, _MatchSet):
            matter_climate.SUPPORT_FAN_MODE_DEVICES = _MatchSet(
                fan, vendors, set(pairs)
            )
        else:
            fan._vendors |= vendors
            fan._pairs |= pairs

        _LOGGER.info(
            "Auto-enabling Matter Dry/Fan-only for vendors %s%s",
            ", ".join(f"0x{v:04X}" for v in sorted(vendors)),
            (
                " + " + ", ".join(f"(0x{v:04X}, 0x{p:04X})" for v, p in sorted(pairs))
                if pairs
                else ""
            ),
        )

        # Recompute features on already-created climate entities so the modes appear without a
        # full restart (the allowlists are read live in _calculate_features()).
        for entry in hass.config_entries.async_entries("matter"):
            hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
    except Exception:  # noqa: BLE001 - never let an HA-internals change break boot
        _LOGGER.exception(
            "Failed to patch the Matter climate Dry/Fan allowlists "
            "(HA internals may have changed); Dry/Fan modes will not be added"
        )

    return True
