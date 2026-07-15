# Matter Extra HVAC Modes

A small Home Assistant custom integration that unlocks the Matter A/C behaviours HA hides behind
hardcoded allow-lists: the **Dry** and **Fan-only** HVAC modes, a **single target temperature**
(instead of a heat/cool range), and a **whole-degree setpoint step** — for any Matter
thermostat/air-conditioner HA doesn't recognise out of the box.

## Why this exists

The Matter Thermostat cluster has feature flags for Heating, Cooling and Auto — but **not** for
Dry or Fan-only. So Home Assistant decides whether to expose those two modes — and whether a device
uses a single setpoint or a heat/cool range, and its setpoint step — from **hardcoded allow-lists**
of `(vendor_id, product_id)` pairs in `homeassistant/components/matter/climate.py`
(`SUPPORT_DRY_MODE_DEVICES`, `SUPPORT_FAN_MODE_DEVICES`, `SINGLE_SETPOINT_DEVICES`).

If your device uses the Matter **test** vendor id `0xFFF1` — common for DIY / ESP32 / `esp-matter`
A/C bridges — it will never be on those lists, so Dry/Fan never appear, you get a heat/cool range
instead of one target temp, and 0.5° steps — even though the firmware reports and accepts all of
it. This is a known limitation: see
[home-assistant/core#135124](https://github.com/home-assistant/core/issues/135124).

You *can* edit HA's core `climate.py`, but that edit is **wiped on every HA upgrade**. This
integration does the same thing from `custom_components/`, so it **survives upgrades**, applies
robustly regardless of whether the Matter integration loads before or after it, and is fully
`try/except`-guarded so a future HA refactor can't break your boot.

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/AndrewDemsDS/ha-matter-extra-hvac-modes`, category **Integration**.
2. Install **Matter Extra HVAC Modes**.
3. Add to `configuration.yaml`:
   ```yaml
   matter_extra_hvac_modes:
   ```
4. Restart Home Assistant.

Manual install: copy `custom_components/matter_extra_hvac_modes/` into your HA
`config/custom_components/`, add the line above, restart.

> **The `matter_extra_hvac_modes:` line in `configuration.yaml` is required.** Without it HA never
> loads the integration (it has no config-flow UI) and nothing changes — this is the most common
> "it didn't work" cause.

## Automatic — no per-device setup

With just `matter_extra_hvac_modes:` (no options) it unlocks **every Matter climate device whose
vendor id is `0xFFF1`** — the Matter *test* vendor used by virtually all DIY / ESP32 / esp-matter
builds — enabling Dry, Fan-only, single-setpoint, and (unless you set a step) leaving HA's default
step. So all your DIY A/Cs get the full mode set with **zero configuration**, regardless of product
id.

## Configuration (all optional)

```yaml
matter_extra_hvac_modes:
  # ── WHICH devices to unlock (any match wins) ──
  vendors: [0xFFF1]              # every product of these vendor ids (default: [0xFFF1])
  devices:                       # explicit [vendor_id, product_id] pairs, for real vendors
    - [0x1234, 0x5678]
  all_matter_climates: false     # true = apply to EVERY Matter climate, any vendor (fully universal)

  # ── WHAT to unlock (defaults shown) ──
  dry: true                      # add HVACMode.DRY
  fan: true                      # add HVACMode.FAN_ONLY
  single_setpoint: true          # one target temperature instead of a heat/cool range
  target_temperature_step: 1.0   # whole-degree steps (omit to leave HA's per-device default)
```

**Device selection** — a device is unlocked if *any* of these match:
- **`vendors`** — all A/Cs from these vendor ids (decimal or `0x` hex). Default `[0xFFF1]`; set `[]`
  to rely only on `devices`.
- **`devices`** — explicit `[vendor_id, product_id]` pairs, for devices on a real (non-test) vendor.
- **`all_matter_climates: true`** — the universal escape hatch: unlock **every** Matter climate
  entity regardless of vendor/product. Use when you don't want to enumerate ids at all.

**What gets unlocked** — each toggle independently:
- **`dry` / `fan`** — add those HVAC modes (default on).
- **`single_setpoint`** — present one target temperature instead of a heat/cool range (default on).
- **`target_temperature_step`** — force a setpoint step (e.g. `1.0`). This is a **class-level**
  default read by *all* Matter climate entities, so it applies fleet-wide; omit it to keep HA's
  per-device default. Only Matter climates are affected.

Only Matter **climate** entities are ever touched, so enabling a whole vendor (or even
`all_matter_climates`) is safe — a non-A/C device simply has no climate entity to change.

Find a device's vendor/product id in **Settings → Devices → your Matter device → Device info**, or
via the Matter Server (`Basic Information` cluster, attributes `0x0002` / `0x0004`).

## How it works

It replaces HA's allow-list sets with a small vendor-aware wrapper (`(vendor_id, _) in set` is true
for your configured vendors / pairs, or always true under `all_matter_climates`), sets the setpoint
step if you asked for one, then reloads the Matter config entry so climate entities recompute their
supported modes. The patch is applied at import, at setup, and again once HA has fully started
(via `async_at_started`) — so it works whether the Matter integration loads before or after this
one, including when a slow cloud integration delays startup past the "started" event. No devices, no
polling, no cloud — just an idempotent one-shot patch.

## Caveats

- It depends on Home Assistant internals (the module-level allow-list sets and
  `MatterClimate._attr_target_temperature_step`). If a future HA release renames or removes them,
  the patch is skipped (logged, never fatal) and you'll want a new version — open an issue.
- `target_temperature_step` is fleet-wide (see above); leave it unset if you have Matter climates
  that should keep different steps.
- The proper long-term fix is HA detecting these modes dynamically (see the linked issue). If that
  lands, this integration is no longer needed.

## AI assistance

Portions of this project were written with AI assistance.

## License

[MIT](LICENSE) © Andreas Demosthenous
