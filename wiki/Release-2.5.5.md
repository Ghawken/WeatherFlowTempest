<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.5.5

**Released:** 2026-05-31
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

`delta_t` and `heat_index` now correctly honour the device temperature unit preference. Previously both states always displayed in Celsius regardless of whether the device was set to Fahrenheit.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Changes

### Fix `delta_t` temperature unit conversion

**Problem:** `delta_t` (the difference between air temperature and wet-bulb temperature) was listed in `_FIXED_SPECS` with a hardcoded `Δ°C` label, so it never converted to Δ°F even when the device's temperature unit was set to Fahrenheit.

**Fix:** Moved `delta_t` out of `_FIXED_SPECS` and into the standard unit conversion pipeline:

| Temperature preference | Value | Display |
|---|---|---|
| Celsius | Raw Δ°C from pyweatherflowudp | `2.1 Δ°C` |
| Fahrenheit | Δ°C × 1.8 (differential — no +32 offset) | `3.8 Δ°F` |

The public station path also hardcoded `Δ°C`; that is corrected to match the device's temperature unit preference.

**Why ×1.8 and not a Pint `.to("degF")` call?**

`delta_t` is a *temperature differential*, not an absolute temperature. Converting `Δ1 °C` → `Δ°F` requires multiplying by 1.8. Using Pint's `.to("degF")` on a `degC` quantity would add the 32 °F offset, producing a wrong result. The manual factor of 1.8 avoids this.

---

### Fix `heat_index` stale Celsius when conditions are not met

**Problem:** pyweatherflowudp returns `None` for `heat_index` when the temperature is below 80 °F or relative humidity is below 40 %. When that happens the plugin skips writing the state entirely, leaving whatever value was last written. If the user had previously been in Celsius mode and then switched to Fahrenheit while conditions were below the heat index threshold, the state would show the stale Celsius reading indefinitely.

**Fix:** When `device.heat_index` is `None`, the plugin now explicitly writes `0` with the correct unit symbol for the current temperature preference. This clears any stale reading.

| Condition | State written |
|---|---|
| `device.heat_index` is a valid value | Converted to °C or °F per preference |
| `device.heat_index` is `None` (below threshold) | `0 °C` or `0 °F` — stale value cleared |

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required.
- On the first observation after plugin reload, `delta_t` and `heat_index` will update with correctly converted values.
- If `delta_t` had previously been showing Δ°C and you are set to Fahrenheit, it will now show Δ°F from the next UDP observation.
- `heat_index` will show `0 °F` (or `0 °C`) when conditions are not met, rather than the previous valid reading.
