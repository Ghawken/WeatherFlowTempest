<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.5.8

**Released:** 2026-06-08
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

Fixes three separate bugs that caused `last_strike_distance` and `last_strike_time` to remain empty or stale during active thunderstorms. Fixes Public Tempest Station unit conversion — temperature, wind, pressure, and rain states were always displayed in metric regardless of device configuration. Also adds a Distance Display unit preference (km / mi) to Tempest, Sky, and Air device configuration.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Bug Fixes

### 1. `last_strike_distance` gated behind `include_standard` (web API path)

**Root cause:** The web API field `lightning_strike_last_distance` was only read inside the `include_standard` block. That block only runs when UDP observations are inactive (stale / web-only mode). With a working UDP device, `evt_strike` UDP packets are supposed to keep `last_strike_distance` current — but `evt_strike` is a separate UDP event that can be silently lost even when normal `obs_st` observations are flowing normally. When that happens, the state never updates from either path and stays permanently empty.

**Fix:** Moved `last_strike_distance` to the always-runs section of `_build_web_observation_states`, identical to where `lightning_count_last_1hr` / `lightning_count_last_3hr` already sit. It now refreshes on every web poll regardless of whether UDP is active.

---

### 2. `last_strike_time` had no web source at all

**Root cause:** The WeatherFlow REST API provides `lightning_strike_last_epoch` — a Unix timestamp of the most recent strike — in every observation response. The plugin never read this field. `last_strike_time` could only ever be populated by UDP `evt_strike` packets. If those don't arrive (see bug 1), the state stays permanently empty with no fallback.

**Fix:** Added `lightning_strike_last_epoch → last_strike_time` extraction in the always-runs section, converting the Unix epoch to a UTC datetime string.

---

### 3. UDP strike events logged at DEBUG only (observability gap)

**Root cause:** The `_on_strike` handler emitted its summary at `DEBUG` level. In normal (non-debug) operation, there was no log evidence that `evt_strike` UDP packets were arriving at all, making it impossible to distinguish "strikes are happening but states aren't updating" from "no strike packets are arriving."

**Fix:** Promoted to `INFO` — every UDP strike now logs `distance=X  energy=Y` at INFO level.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Bug Fix

### 4. Public Tempest Station ignored unit preferences (always showed metric)

**Root cause:** `_build_public_obs_states` assumed the `observations/station/{id}` API would honour unit query parameters (`units_temp=f`, `units_wind=mph`, etc.) and return values already in the user's preferred units. In practice the endpoint returns metric values regardless of what unit parameters are sent — meaning a Public Station configured for Fahrenheit, mph, and inches still displayed °C, m/s, and mm.

**Fix:** Aligned the Public Tempest Station path with how personal stations have always worked:

| | Before | After |
|---|---|---|
| API fetch | Dynamic unit params sent, API expected to convert | Always requests metric (`units_temp=c`, `units_wind=mps`, `units_pressure=mb`, `units_precip=mm`, `units_distance=km`) |
| Conversion | Assumed done by API; values written as-is | Plugin converts via `_add_u` / Pint — identical to `_build_web_observation_states` |
| `last_strike_distance` | Hardcoded `km` symbol | `_add_u` with `"distance"` category — converts to km or mi per device setting |

**Affected states (now correctly converted):**

| State | API field | Metric unit in | Converts to |
|---|---|---|---|
| `air_temperature` | `air_temperature` | °C | °C or °F |
| `dew_point_temperature` | `dew_point` | °C | °C or °F |
| `wet_bulb_temperature` | `wet_bulb_temperature` | °C | °C or °F |
| `feels_like_temperature` | `feels_like` | °C | °C or °F |
| `heat_index` | `heat_index` | °C | °C or °F |
| `wind_chill_temperature` | `wind_chill` | °C | °C or °F |
| `delta_t` | `delta_t` | Δ°C | Δ°C or Δ°F |
| `station_pressure` | `station_pressure` | hPa | hPa, mmHg, or inHg |
| `sea_level_pressure` | `sea_level_pressure` | hPa | hPa, mmHg, or inHg |
| `wind_average` / `wind_speed` | `wind_avg` | m/s | m/s, km/h, kn, or mph |
| `wind_gust` | `wind_gust` | m/s | m/s, km/h, kn, or mph |
| `wind_lull` | `wind_lull` | m/s | m/s, km/h, kn, or mph |
| `rain_today` | `precip_accum_local_day` | mm | mm or in |
| `rain_yesterday` | `precip_accum_local_yesterday` | mm | mm or in |
| `rain_last_1hr` | `precip_accum_last_1hr` | mm | mm or in |
| `last_strike_distance` | `lightning_strike_last_distance` | km | km or mi |

Fixed-unit states (UV, solar radiation, illuminance, relative humidity, elevation, air density) are unchanged.

**Existing devices:** No configuration changes required. Values will now display in whatever units are set in Edit Device — if you've had the device configured for Fahrenheit/mph/inches all along, they will now correctly show those units after the plugin reloads.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## New Feature

### Distance Display unit preference for Tempest, Sky, and Air devices

**Problem:** `last_strike_distance` and `lightning_strike_average_distance` were always displayed in kilometres, regardless of how the device was otherwise configured. The Public Tempest Station device type already had a Distance Display preference; Tempest, Sky, and Air did not.

**Fix:**

- Added a **Distance Display** field (Kilometres / Miles) to the ConfigUI of Tempest, Sky, and Air device types.
- `_get_unit_prefs()` now reads `distUnit` from the device's saved properties (defaulting to `"km"` for existing devices).
- Lightning distance states are converted to the selected unit before being written to Indigo.
- The per-strike INFO log line shows the distance in the selected unit.

**Existing devices** default to km — no action required unless you want miles.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Lightning State Reference

The WeatherFlow lightning sensor uses radio frequency detection to identify return strokes. Its data reaches the plugin through three separate pathways that update at different times and answer different questions — mixing them up is the source of most lightning-related confusion.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

### Per-observation states (updated every ~1 minute with each `obs_st` packet)

| State | Typical value | What it means |
|---|---|---|
| `lightning_strike_count` | **0** most of the time; 1–5+ during active storms | Number of strikes detected within the **current 1-minute observation window**. Resets to `0` at the start of every new observation. **This is a window count, not a running total.** |
| `lightning_strike_average_distance` | **0** when no strikes; 1–40 during storms | Average distance (in your chosen unit) of all strikes within that same 1-minute window. Only meaningful when `lightning_strike_count > 0`. Reads `0` whenever the count is zero — not the same as a strike at 0 km. |

> **`lightning_strike_count = 0` between strike-active minutes is completely normal.** The sensor reports a fresh window count every minute; if no strike was detected in that minute, the count is 0. For "is there a storm right now?", use `lightning_count_last_1hr` (requires Web API token).

---

### Per-strike states (updated when a strike is detected)

These states are written by two sources that now both feed the same states:

- **UDP path** — `evt_strike` packets arrive separately from observations and can occasionally be lost even when `obs_st` packets are flowing normally.
- **Web API path** (new in v2.5.8, requires API token) — `lightning_strike_last_distance` and `lightning_strike_last_epoch` are present in every observation response and now always update these states as a fallback.

| State | Source | Typical value | What it means |
|---|---|---|---|
| `last_strike_distance` | UDP + Web† | Blank until first strike, then persists | Distance of the **single most recent strike**. Stays set after the storm ends — always read alongside `last_strike_time` to judge how recent it is. Blank if the sensor could not determine range (minimum reliable detection ~1 km; very close strikes may report null). |
| `last_strike_energy` | **UDP only** | Blank until first strike, then persists | A dimensionless relative intensity value from the sensor hardware. **Not joules or watts** — it's an internal metric roughly proportional to return-stroke intensity. Useful for comparing strikes within a storm; meaningless as an absolute number. Blank when the sensor reported null. |
| `last_strike_time` | UDP + Web† | Blank until first strike, then persists | UTC timestamp of the most recent detected strike. Persists until the next strike — use this to determine whether `last_strike_distance` is from a current storm or a storm days ago. |

> † Web API fallback requires a valid API token in Plugin Preferences. Without a token, these states are only populated by UDP `evt_strike` packets.

---

### Rolling window counts (updated every ~60 s from the Web API)

Requires a valid API token. These are quality-controlled by the WeatherFlow cloud.

| State | Typical value | What it means |
|---|---|---|
| `lightning_count_last_1hr` | 0 most of the time; accumulates during storms | Count of all strikes in the rolling last 60 minutes. The most reliable indicator of current storm activity. Use this in triggers: "if `lightning_count_last_1hr` > 0". |
| `lightning_count_last_3hr` | 0 most of the time; higher during extended activity | 3-hour rolling window. Useful for tracking an approaching or receding storm system. |

---

### Quick reference: which state to use for what

| Question | State to use |
|---|---|
| Is there lightning happening right now? | `lightning_count_last_1hr > 0` |
| How far away was the most recent strike? | `last_strike_distance` (with `last_strike_time` to confirm it's current) |
| How many strikes were in the last minute? | `lightning_strike_count` |
| How close is the storm on average? | `lightning_strike_average_distance` (when `lightning_strike_count > 0`) |
| How intense was the last strike? | `last_strike_energy` (relative comparison only) |
| Is the storm getting closer or moving away? | Compare `lightning_count_last_1hr` vs `lightning_count_last_3hr` |

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required for any device type.
- **Public Tempest Station:** Values will now display in the units configured in Edit Device. If you have had the device set to Fahrenheit/mph/inches and it was showing metric, it will immediately show correct values after the plugin reloads — no reconfiguration needed.
- **Lightning states** (`last_strike_distance`, `last_strike_time`) now populate from the web API even when UDP strike events are not arriving — requires an API token.
- **Distance Display for Tempest/Sky/Air:** Existing devices default to km. To switch to miles, Edit Device → **Distance Display → Miles (mi)**.
