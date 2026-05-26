<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.5.2

**Released:** 2026-05-26
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

Two improvements to how the plugin handles an offline personal Tempest station:

1. **Offline detection rewritten** — the 2.5.1 implementation used a `better_forecast` field that proved unreliable; a correct documented API endpoint is now used instead.
2. **Device error state** — when a station goes stale or offline, the Indigo device turns red in the UI with a status string. Clears automatically when the station recovers.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Changes

### Personal Station Offline Detection Rewritten

**Problem (2.5.1 regression):** The 2.5.1 fix for stale web data worked correctly for Public Tempest Station devices but not for personal stations. The personal web poller used `better_forecast.current_conditions.time` as the observation timestamp — a field that always reflects the time WeatherFlow generated the API response (2–3 seconds ago), not when the Tempest device last transmitted. Additionally, `better_forecast.station.is_station_online` returns `True` even when the device has a completely flat battery.

The result: the 10-minute age gate in 2.5.1 never fired for personal stations, and stale cached data continued to be written to Indigo states when a station was offline.

**Investigation:** A complete audit of available WeatherFlow REST API endpoints was performed against a live flat-battery device:

| Endpoint / Field | Value when offline | Reliable? |
|---|---|---|
| `better_forecast` → `current_conditions.time` | Always 2–3 s | ❌ API generation time |
| `better_forecast` → `station.is_station_online` | `True` | ❌ Always true |
| `better_forecast` → `station.state` | `1` | ❌ Static config value |
| `/stations/{id}` → device fields | No status fields | ❌ Config metadata only |
| `/diagnostics/{id}` | Accurate | ❌ Requires partner API key |
| `/observations/stn/{id}` → `obs` | `[]` (empty list) | ✅ Definitive offline signal |

**Fix:** Every web poll cycle now makes two API calls:

1. **`better_forecast`** — unchanged, provides current conditions data for device states.
2. **`/observations/stn/{station_id}?api_key={token}&bucket=1`** — the documented personal station observations endpoint. `bucket=1` returns the latest 1-minute record only. When the station is offline, `obs: []` is returned.

Offline detection logic:

- **`obs: []`** → station has no recent observations — update is rejected.
- **`obs[-1][0]`** → timestamp of the most recent observation record. If more than **10 minutes old**, update is also rejected (secondary age gate).
- **Normal operation** — observation age is logged at Debug level:
  ```
  station 183063: /observations/stn status={'status_code': 0, 'status_message': 'SUCCESS'}  obs count=1
  My Tempest: web observation age 47 s (0.8 min)
  ```

**Note on endpoint naming:** `/observations/stn` is the documented personal station endpoint in the WeatherFlow API reference. `/observations/station` (used for public stations) also returns `obs: []` when offline, but is the public-facing endpoint. Using the correct personal endpoint avoids any reliance on undocumented behaviour.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

### Device Error State When Station is Offline

When a personal station's data is stale or absent, the plugin now marks the Indigo device with an error state so it is immediately visible in the Indigo client UI (device row turns red, status column shows the error string).

**Two thresholds:**

| Stale duration | `deviceStatus` state | Indigo error state |
|---|---|---|
| < 10 minutes | unchanged | none |
| 10 – 30 minutes | `Stale data` | `Stale data` (device turns red) |
| > 30 minutes | `Offline` | `Offline` (device turns red) |

**Recovery is automatic** — on the next successful poll after the station comes back online, the error state is cleared and all device states resume updating normally. No manual action required.

**Cleared at startup** — if the plugin is reloaded or Indigo restarts while a station is offline, any lingering error state from the previous session is cleared immediately on `deviceStartComm` and set fresh once the first poll completes.

Log output during an offline event:

```
Warning: My Tempest: station offline — no recent observations (stale 0 min)
Warning: My Tempest: station offline — no recent observations (stale 12 min)   ← device now shows "Stale data"
Warning: My Tempest: station offline — no recent observations (stale 31 min)   ← device now shows "Offline"
My Tempest: web observation age 43 s (0.7 min)                                 ← station recovered, error cleared
```

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required. Both fixes are automatic.
- Reload the plugin after updating to clear any stale error state from prior versions.
- The Public Tempest Station offline detection from 2.5.1 is unchanged and unaffected.
