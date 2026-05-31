<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.5.4

**Released:** 2026-05-30
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

Rain accumulation is now cleanly separated into two independent tracks. The web API provides rain-check corrected daily totals in `rain_today` / `rain_yesterday`. The device provides raw local totals in `rain_today_local` / `rain_yesterday_local`. Neither track can corrupt the other.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Changes

### Separate Local and Web Rain Accumulation

**Background:** Two independent paths were writing to the same `rain_today` state:

- **UDP path** — reads the hub's own daily rain counter (hub index 18, resets at local midnight). Falls back to accumulating per-minute rain values when the hub sends shorter packets in power-save / low-battery mode (e.g. when `Precipitation Failed` appears in sensor_status).
- **Web API path** — reads `precip_accum_local_day` from WeatherFlow, which is always rain-check corrected and typically the more accurate total.

With both paths writing `rain_today`, the state alternated every ~60 seconds between the raw local value and the web value. In power-save mode this was especially visible: local showed `"accumulated"` while web showed a slightly different corrected total.

Additionally, the fallback accumulation used `rain_today_raw_mm` as its running baseline — the same state the web API wrote to. Each web poll would shift the baseline, causing the next per-minute delta to be added on top of a different starting point.

**Fix — fully separated write ownership:**

| State | Written by | Contains |
|---|---|---|
| `rain_today` | **Web API only** | Rain-check corrected daily total |
| `rain_today_raw_mm` | **Web API only** | Same, in raw mm |
| `rain_yesterday` | **Web API only** | Rain-check corrected yesterday total |
| `rain_today_local` | **UDP only** | Device daily total (not rain-check corrected) |
| `rain_today_local_raw_mm` | **UDP only** | Same, in raw mm — accumulation baseline |
| `rain_yesterday_local` | **UDP only** | Device yesterday total (captured at midnight) |
| `rain_today_source` | **UDP only** | `"hub"` or `"accumulated"` |

`rain_today_source` values:

| Value | Meaning |
|---|---|
| `hub` | Hub index 18 present — device's own authoritative daily counter |
| `accumulated` | Hub index 18 absent (power-save / sensor fault) — plugin accumulating per-minute values as fallback |

**Web API is the primary source for most users.** `rain_today` shows the rain-check corrected total and is the recommended state for automations. `rain_today_local` is available when you want the raw device value or need a value independent of web availability.

**Midnight rollover:** at midnight the plugin captures `rain_today_local_raw_mm` into `rain_yesterday_local`. The web API writes `rain_yesterday` from `precip_accum_local_yesterday`. Both yesterday states update independently.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required.
- The four new states are added automatically on the first observation after the plugin is reloaded.
- `rain_today` and `rain_yesterday` now update only when the web API polls (~60 s). They no longer update every UDP observation. Existing automations using these states are unaffected — values are the same, just sourced exclusively from web.
- If you were using `rain_today` as a real-time per-minute counter, switch to `rain_today_local` for that use case.
