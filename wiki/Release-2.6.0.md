<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.6.0

**Released:** 2026-09-21
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

Two new rain accumulation states — **`rain_lastweek`** and **`rain_lastmonth`** — rolling 7-day and 30-day totals, ideal for irrigation decisions ("did it rain enough this week to skip watering?"). The Tempest API does not provide these, so the plugin calculates them itself from a persisted daily history.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## New Features

### `rain_lastweek` and `rain_lastmonth` states

Available on **Tempest** and **Sky** devices (Air has no rain sensor).

| State | Trigger label | Window |
|---|---|---|
| `rain_lastweek` | Rain Last 7 Days (rolling total, includes today) | Today + previous 6 days |
| `rain_lastmonth` | Rain Last 30 Days (rolling total, includes today) | Today + previous 29 days |

Both respect the device's **Rainfall unit preference** (mm or inches), the same as `rain_today`.

**How it works:**

- Each observation records today's running rain total into a per-day history
- At midnight rollover, yesterday's final total is locked in — using the same rollover detection that drives `rain_yesterday_local`
- The rolling sums are recomputed on every observation
- History entries older than 31 days are pruned automatically

**Persistence:**

The daily history is saved to a JSON file:

```
{Indigo install folder}/Preferences/Plugins/{plugin_id}_rain_history.json
```

It survives plugin restarts, Indigo restarts, and machine reboots. Writes are atomic (temp file + rename), so a crash mid-write cannot corrupt existing history.

**Example — irrigation trigger:**

Device State Changed → *Rain Last 7 Days (rolling total, includes today)* → use in a schedule's condition: "only run sprinklers if `rain_lastweek` is less than 10".

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Notes & Caveats

- **History only accumulates while the plugin is running.** If the plugin (or Indigo) is stopped for a full day, that day records nothing — the day is missed, not corrupted. Totals resume correctly when the plugin restarts.
- Totals are built from the **local (UDP) device values** — not rain-check corrected — consistent with `rain_today_local`.
- **After first upgrade to 2.6.0**, `rain_lastweek` starts equal to today's rain and grows one day at a time. After 7 days of running it is a true weekly total; after 30 days, a true monthly total.
- A past day's recorded value can never shrink — this protects the history against a hub reset mid-day overwriting an already-captured total with a smaller number.
- Web-only devices and Public Tempest Station devices do not receive these states (no UDP data path).

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required. The new states appear automatically after the plugin restarts and the first observation arrives.
- The rain history JSON file is created on first observation after upgrade.
