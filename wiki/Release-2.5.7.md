<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.5.7

**Released:** 2026-06-04
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

Completes the unit-label cleanup started in 2.5.6. The Conditions menu (used when adding conditions to Triggers and Schedules) no longer shows hardcoded metric unit annotations alongside state names.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Changes

### Conditions menu — remove hardcoded unit annotations from `ControlPageLabel`

**Background:** Indigo uses two separate label fields in `Devices.xml`:

| Field | Used by |
|---|---|
| `TriggerLabel` | Triggers tab — state picker when creating a trigger based on a device state change |
| `ControlPageLabel` | Conditions tab — state picker when adding an "if device" condition to a Trigger or Schedule |

Release 2.5.6 removed hardcoded metric units from `TriggerLabel` but did not touch `ControlPageLabel`. As a result, the Conditions tab still showed entries like **"Air Temp °C"**, **"Wind Speed m/s"**, **"Pressure mbar"** regardless of the device's unit setting.

**Fix:** Removed the hardcoded unit suffix from all variable-unit `ControlPageLabel` entries across the Tempest, Sky, Air, and Public Station device blocks.

Examples:

| Before | After |
|---|---|
| `Air Temp °C` | `Air Temp` |
| `Wind Speed m/s` | `Wind Speed` |
| `Pressure mbar` | `Pressure` |
| `SLP mbar` | `Sea Level Pressure` |
| `Vapor Press mbar` | `Vapor Pressure` |
| `Rain Accum mm` | `Rain Accum` |
| `Rain Rate mm/h` | `Rain Rate` |
| `Lightning Dist km` | `Lightning Dist` |
| `Last Strike km` | `Last Strike Dist` |
| `Wind Avg m/s` | `Wind Avg` |
| `Wind Gust m/s` | `Wind Gust` |
| `Wind Lull m/s` | `Wind Lull` |
| `Heat Index °C` | `Heat Index` |
| `Delta T °C` | `Delta T` |

Fixed-unit labels (`%`, `W/m²`, `lx`, `UV`, `V`, `dBm`, `°`) are unchanged. Existing conditions and triggers continue to work without modification.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required.
- Label changes take effect after plugin reload.
- Existing triggers and conditions are unaffected — only the display text in the state picker menus changes.
