<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.6.2

**Released:** 2026-10-09
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

Two new comparison states — **`rain_prevweek`** and **`rain_prevmonth`** — covering the rolling window *before* the existing `rain_lastweek` / `rain_lastmonth` windows. Useful for trend comparisons like "was this month wetter than the month before?"

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## New Features

### `rain_prevweek` and `rain_prevmonth` states

Available on **Tempest** and **Sky** devices. Both respect the device's Rainfall unit preference (mm or inches).

The four rolling rain states now cover 60 contiguous days with no overlap and no gaps:

| State | Trigger label | Window |
|---|---|---|
| `rain_lastweek` | Rain Last 7 Days (rolling total, includes today) | Days 0–6 (today + previous 6) |
| `rain_prevweek` | Rain Previous 7 Days (rolling, days 7-13 back) | Days 7–13 |
| `rain_lastmonth` | Rain Last 30 Days (rolling total, includes today) | Days 0–29 (today + previous 29) |
| `rain_prevmonth` | Rain Previous 30 Days (rolling, days 30-59 back) | Days 30–59 |

All windows roll forward one day at a time at midnight.

**Which state for which job:**

- **Irrigation scheduling** → `rain_lastweek` / `rain_lastmonth` — "how much rain fell in the past 7 / 30 days?"
- **Trend comparison** → `rain_prevweek` / `rain_prevmonth` — "how does that compare to the week / month before?"

### History retention extended

The persisted daily rain history (introduced in 2.6.0) now keeps **62 days** instead of 31, so the previous-30-day window is fully covered. Existing history files carry over untouched — the extra days simply accumulate from now on.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Notes & Caveats

- Same caveats as 2.6.0: history only accumulates while the plugin is running, and totals use the local (UDP) device values (not rain-check corrected).
- **Ramp-up:** `rain_prevweek` is accurate once ~14 days of history exist. `rain_prevmonth` needs ~60 days — if you installed 2.6.0 recently it will show a partial total until a full 60 days of history have built up.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required. The new states appear automatically after the plugin restarts and the first observation arrives.
