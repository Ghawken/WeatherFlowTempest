<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.5.6

**Released:** 2026-06-03
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

`heat_index` and `wind_chill_temperature` now show blank when conditions are not met. Trigger/condition menus no longer show hardcoded `°C`, `mbar`, `m/s`, or `mm` unit labels.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Changes

### Heat Index and Wind Chill — blank (None) when conditions are not met

pyweatherflowudp returns `None` for these states when conditions are outside the calculation range:

| State | Returns `None` when |
|---|---|
| `heat_index` | temperature < 80 °F or relative humidity < 40 % |
| `wind_chill_temperature` | temperature > 50 °F or wind speed < 3 mph |

Previously, when the value was `None` the plugin skipped writing the state entirely — leaving whatever value was last recorded. This meant a stale reading persisted indefinitely, and a unit preference change (e.g. Celsius → Fahrenheit) would never be reflected until conditions happened to come back into range.

The plugin now always writes the state when `None` is received, storing `None` as the value with a blank display string:

| Situation | `value` | Display |
|---|---|---|
| Conditions met — valid reading | `95.3` | `95.3 °F` |
| Conditions not met — `None` returned | `None` | *(blank)* |

The `None` write is immediate — no stale value lingers after a weather change or unit preference update. Because these states are not typically used in numeric triggers, the `None` value is appropriate; the blank display clearly communicates "not applicable" rather than a misleading `0`.

---

### Trigger/condition menus — remove hardcoded unit annotations

The Indigo trigger and condition UI shows the state's `TriggerLabel` from `Devices.xml` in the state picker dropdown. These labels were annotated with hardcoded metric units — `(°C)`, `(mbar)`, `(m/s)`, `(mm)` — regardless of the device's actual unit setting. A device set to Fahrenheit would show "Air Temperature (°C)" in the trigger dropdown, creating confusion about what unit to enter for the comparison threshold.

The unit suffix has been removed from all variable-unit `TriggerLabel` entries across the Tempest, Sky, Air, and Public Station device blocks. Fixed-unit labels (`%`, `W/m²`, `lx`, `UV`, `V`, `dBm`, `°`) are unchanged.

Examples:

| Before | After |
|---|---|
| `Air Temperature (°C)` | `Air Temperature` |
| `Wind Speed (m/s)` | `Wind Speed` |
| `Station Pressure (mbar)` | `Station Pressure` |
| `Rain Rate (mm/h)` | `Rain Rate` |
| `Heat Index (°C)` | `Heat Index` |
| `Delta T (°C)` | `Delta T` |

The active unit is always visible in the state's current `uiValue` (e.g. `32.8 °F`) and is also stored in the `unit_temperature`, `unit_pressure`, `unit_wind`, and `unit_rain` states.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required.
- `TriggerLabel` changes take effect after plugin reload — existing triggers continue to work unchanged.
- On the next observation after reload, `heat_index` and `wind_chill_temperature` will show blank if conditions are not currently met, clearing any stale reading.
