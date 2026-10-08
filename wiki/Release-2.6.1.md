<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.6.1

**Released:** 2026-10-08
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

Two usability improvements requested by users:

1. **State lists are now alphabetical** — the Device State lists in trigger, condition, and control page menus now sort A→Z instead of being grouped by sensor category.
2. **New `last_report_local` state** — the last report timestamp formatted in your Mac's local time and locale, alongside the existing UTC `last_report`.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Improvements

### Alphabetical state lists

**Why weren't they alphabetical before?** Indigo displays device states in the exact order the plugin declares them — Indigo itself does no sorting. Previously the plugin declared states grouped by category (temperature, atmospheric, rain, lightning, wind, diagnostics...), which made sense in the source but made states hard to find in Indigo's long dropdown menus.

As of 2.6.1 all states are declared alphabetically for every device type — Tempest, Sky, Air, Hub, and Public Tempest Station. This affects:

- The state list when creating a **Device State Changed** trigger
- The state list in **condition** menus
- The state picker when building **Control Pages**
- The Custom States display order in the device UI

No state names or values changed — only the ordering. Existing triggers, conditions, and control pages are unaffected.

### New state — `last_report_local`

Available on **Tempest**, **Sky**, and **Air** devices.

| State | Trigger label | Example value |
|---|---|---|
| `last_report` | Last Report Time (UTC) | `2026-10-08 03:21:05+00:00` *(unchanged)* |
| `last_report_local` | Last Report Time (Local) | `08/10/2026 14:21:05` |

`last_report_local` converts the sensor's last report timestamp to your Mac's local time zone and formats it using the system locale — so date order (day/month vs month/day) and time format follow your macOS region settings automatically.

The existing UTC `last_report` state is unchanged, so anything already using it keeps working.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required. The new state appears automatically after the plugin restarts and the first observation arrives.
- The reordered state lists take effect as soon as the plugin reloads.
