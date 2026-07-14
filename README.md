# Matter Extra HVAC Modes

A tiny Home Assistant custom integration that adds the **Dry** and **Fan-only** HVAC modes for
Matter thermostats/air-conditioners that HA doesn't recognise out of the box.

## Why this exists

The Matter Thermostat cluster has feature flags for Heating, Cooling and Auto — but **not** for
Dry or Fan-only. So Home Assistant decides whether to expose those two modes from a **hardcoded
allowlist** of `(vendor_id, product_id)` pairs in `homeassistant/components/matter/climate.py`
(`SUPPORT_DRY_MODE_DEVICES` / `SUPPORT_FAN_MODE_DEVICES`).

If your device uses the Matter **test** vendor id `0xFFF1` — common for DIY / ESP32 / `esp-matter`
A/C bridges — it will never be on that list, so Dry/Fan never appear even though the firmware
reports and accepts them. This is a known limitation: see
[home-assistant/core#135124](https://github.com/home-assistant/core/issues/135124).

You *can* edit HA's core `climate.py` to add your device, but that edit is **wiped on every HA
upgrade**. This integration does the same thing from `custom_components/`, so it **survives
upgrades**, and it's wrapped in `try/except` so a future HA refactor can't break your boot.

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/AndrewDemsDS/ha-matter-extra-hvac-modes`, category **Integration**.
2. Install **Matter Extra HVAC Modes**.
3. Add to `configuration.yaml`:
   ```yaml
   matter_extra_hvac_modes:
   ```
4. Restart Home Assistant.

Manual install: copy `custom_components/matter_extra_hvac_modes/` into your HA `config/custom_components/`, add the line above, restart.

## Configuration

Defaults to `(0xFFF1, 0x8000)`. To target different / additional devices, list `[vendor_id, product_id]` pairs (decimal or `0x` hex both work):

```yaml
matter_extra_hvac_modes:
  devices:
    - [0xFFF1, 0x8000]
    - [0xFFF1, 0x8001]
```

Find your device's vendor/product id in **Settings → Devices → your Matter device → Device info**,
or via the Matter Server (`Basic Information` cluster, attributes `0x0002` / `0x0004`).

## How it works

On startup it adds your `(vendor_id, product_id)` to `SUPPORT_DRY_MODE_DEVICES` and
`SUPPORT_FAN_MODE_DEVICES`, then reloads the Matter config entry so the climate entities
recompute their supported modes. No devices, no polling, no cloud — just a one-shot patch.

## Caveats

- It depends on Home Assistant internals (the two module-level sets). If a future HA release
  renames or removes them, the patch is skipped (logged, never fatal) and you'll want a new
  version — open an issue.
- The proper long-term fix is HA detecting these modes dynamically (see the linked issue). If
  that lands, this integration is no longer needed.

## AI assistance

Portions of this project were written with AI assistance.

## License

[MIT](LICENSE) © Andreas Demosthenous
