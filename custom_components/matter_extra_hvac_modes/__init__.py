"""Unlock Matter A/C behaviours Home Assistant doesn't expose out of the box.

Matter's Thermostat cluster has no feature flags for **Dry** or **Fan-only**, so HA gates those
modes behind hardcoded `(vendor_id, product_id)` allow-lists in
`homeassistant/components/matter/climate.py` (`SUPPORT_DRY_MODE_DEVICES` /
`SUPPORT_FAN_MODE_DEVICES`). It likewise decides **single-setpoint vs. heat/cool range** and the
**setpoint step** from hardcoded lists. Devices on the Matter *test* vendor `0xFFF1` (nearly all
DIY / ESP32 / esp-matter A/Cs) are never listed, so they get a heat/cool range, 0.5° steps, and
no Dry/Fan — even when the firmware supports all of it. See home-assistant/core#135124.

This integration fixes all of that, configurably:

    matter_extra_hvac_modes:
      # WHICH devices to unlock (any match wins):
      vendors: [0xFFF1]            # every product of these vendor ids (default: [0xFFF1])
      devices: [[0x1234, 0x5678]]  # explicit [vendor_id, product_id] pairs (real vendors)
      all_matter_climates: false   # true = apply to EVERY Matter climate (fully universal)
      # WHAT to unlock (all default true except the step):
      dry: true                    # add HVACMode.DRY
      fan: true                    # add HVACMode.FAN_ONLY
      single_setpoint: true        # one target temp instead of a heat/cool range
      target_temperature_step: 1.0 # whole-degree steps (omit to leave HA's default)

Unlike editing HA's core `climate.py` (wiped on every upgrade) this lives in `custom_components/`
and **survives upgrades**, patches at import + setup + once HA has started (robust against the
Matter entry loading before or after us), and is fully try/except-guarded so an HA-internals
change can never break your boot. Only Matter *climate* entities are ever touched.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

DOMAIN = "matter_extra_hvac_modes"
CONF_VENDORS = "vendors"
CONF_DEVICES = "devices"
CONF_ALL = "all_matter_climates"
CONF_DRY = "dry"
CONF_FAN = "fan"
CONF_SINGLE_SETPOINT = "single_setpoint"
CONF_TEMP_STEP = "target_temperature_step"

# The Matter "test" vendor id — used by virtually every DIY / ESP32 / esp-matter build.
DEFAULT_VENDORS: list[int] = [0xFFF1]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_VENDORS): [vol.Coerce(int)],
                vol.Optional(CONF_DEVICES): [
                    vol.All([vol.Coerce(int)], vol.Length(min=2, max=2))
                ],
                vol.Optional(CONF_ALL): cv.boolean,
                vol.Optional(CONF_DRY): cv.boolean,
                vol.Optional(CONF_FAN): cv.boolean,
                vol.Optional(CONF_SINGLE_SETPOINT): cv.boolean,
                vol.Optional(CONF_TEMP_STEP): vol.Coerce(float),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


class _MatchSet:
    """Drop-in replacement for HA's allow-list `set` with vendor / all matching.

    ``(vendor_id, product_id) in self`` is True when the pair is in the original HA set, is
    explicitly configured, comes from a configured vendor id, or ``match_all`` is set. Behaves
    enough like a set (``in`` / ``add`` / iteration) for HA's usage.
    """

    def __init__(self, wrapped, vendors, pairs, match_all=False):
        self._wrapped = set(wrapped)
        self._vendors = set(vendors)
        self._pairs = set(pairs)
        self._all = match_all

    def __contains__(self, item):
        if self._all:
            return True
        try:
            vendor_id = item[0]
        except (TypeError, IndexError):
            return item in self._wrapped
        return (
            vendor_id in self._vendors or item in self._pairs or item in self._wrapped
        )

    def add(self, item):
        self._pairs.add(item)

    def update(self, items):
        self._pairs.update(items)

    def __iter__(self):
        return iter(self._wrapped | self._pairs)

    def merge(self, vendors, pairs, match_all):
        self._vendors |= set(vendors)
        self._pairs |= set(pairs)
        self._all = self._all or match_all


def _wrap(module, name, vendors, pairs, match_all):
    """Replace module.<name> (a set) with a vendor-aware _MatchSet, or update an existing one."""
    current = getattr(module, name, set())
    if isinstance(current, _MatchSet):
        current.merge(vendors, pairs, match_all)
    else:
        setattr(module, name, _MatchSet(current, vendors, pairs, match_all))


def _apply(conf) -> bool:
    """Patch HA's Matter-climate allow-lists + step (idempotent). Returns True on success."""
    vendors = {int(v) for v in conf.get(CONF_VENDORS, DEFAULT_VENDORS)}
    pairs = {(int(p[0]), int(p[1])) for p in conf.get(CONF_DEVICES, [])}
    match_all = bool(conf.get(CONF_ALL, False))

    try:
        from homeassistant.components.matter import climate as mc

        if conf.get(CONF_DRY, True):
            _wrap(mc, "SUPPORT_DRY_MODE_DEVICES", vendors, pairs, match_all)
        if conf.get(CONF_FAN, True):
            _wrap(mc, "SUPPORT_FAN_MODE_DEVICES", vendors, pairs, match_all)
        if conf.get(CONF_SINGLE_SETPOINT, True) and hasattr(
            mc, "SINGLE_SETPOINT_DEVICES"
        ):
            _wrap(mc, "SINGLE_SETPOINT_DEVICES", vendors, pairs, match_all)

        step = conf.get(CONF_TEMP_STEP)
        if step is not None:
            # Class-level default; only Matter climate entities read it. Applies to all of them,
            # which is fine for a fleet of A/Cs — scope with all_matter_climates=false + a step you
            # want globally, or leave unset to keep HA's per-device default.
            mc.MatterClimate._attr_target_temperature_step = float(step)
        return True
    except Exception:  # noqa: BLE001 - never let an HA-internals change break boot
        _LOGGER.exception(
            "matter_extra_hvac_modes: could not patch Matter climate (HA internals may have "
            "changed); Matter A/C modes will not be unlocked"
        )
        return False


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Patch, then reload the Matter entry once HA has started so the entities rebuild."""
    conf = config.get(DOMAIN) or {}
    _apply(conf)  # early best-effort

    async def _reload_matter(_hass: HomeAssistant) -> None:
        if not _apply(conf):
            return
        entries = hass.config_entries.async_entries("matter")
        _LOGGER.info(
            "matter_extra_hvac_modes: patch applied; reloading %d Matter config entr%s so "
            "climate entities pick up the unlocked modes",
            len(entries),
            "y" if len(entries) == 1 else "ies",
        )
        for entry in entries:
            await hass.config_entries.async_reload(entry.entry_id)

    # Runs immediately if HA is already started (our setup can land after the Matter entry, esp.
    # when a slow cloud integration delays startup), otherwise on the started event.
    async_at_started(hass, _reload_matter)
    return True
