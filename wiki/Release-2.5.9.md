<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.5.9

**Released:** 2026-06-21
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

Two fixes that both cause the same symptom — a false "Stale data" / red-device state — but for different reasons:

1. **Replaced sensor:** If a Tempest was physically replaced but the old serial number remained in the Indigo device config, the plugin polled the offline station forever and received permanently stale data. The poller now detects this, skips the dead serial, and logs a single actionable warning.

2. **Cloud pipeline lag:** After a hub reconnects to the internet following an outage, the WeatherFlow cloud API (`/observations/stn`) can be many hours behind the hub's local UDP broadcast. The plugin was correctly detecting the cloud staleness but incorrectly marking the device red when UDP was flowing fine. The staleness gate now checks for recent UDP activity first and skips the stale mark when the hub is locally reachable.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Bug Fixes

### Fix 1 — Web poller polling a replaced/offline station — permanent "Stale data" error

**Scenario:** A WeatherFlow Tempest sensor is replaced with a new unit. The new sensor has a different serial number (e.g. `ST-00210902`) but the Indigo device configuration still contains the old serial (`ST-00053701`). The WeatherFlow account now has two stations — the old one (offline, no recent data) and the new one (active).

**What happened:**

- The plugin built its serial → station_id map from the WeatherFlow account, finding both the old and new station
- Every web poll queried the OLD station (for `ST-00053701`) and received data that was permanently 23+ hours stale
- The `_on_web_obs` staleness check correctly detected this but had no way to tell the user why — it just set the device status to **"Stale data"** and turned the device red in Indigo
- The warning repeated every poll cycle with no indication of the root cause

**Fix:** On each web poll cycle the plugin now compares the configured serial numbers against the set of sensors currently discovered via UDP. If a configured serial is **not** currently broadcasting on the local network but other ST- sensors **are** present, that serial is skipped and a single warning is logged:

```
WeatherFlow Tempest (ST-00053701): serial not found via UDP — station data is permanently
stale. The device may have been replaced. Active sensor(s) on this network: ST-00210902.
Edit Device and update the serial number.
```

The warning fires once per serial (not every poll). If the device is later discovered via UDP again (e.g. after a hub reboot) the warning resets automatically.

**What to do if you see this warning:** Open the Indigo device, click **Edit Device**, and change the serial number to the active sensor shown in the warning message.

---

### Fix 2 — False "Stale data" / red-device after hub reconnects to internet (cloud pipeline lag)

**Scenario:** A WeatherFlow hub loses its internet connection for several hours (e.g. router reboot, ISP outage). When it reconnects, the WeatherFlow cloud API (`/observations/stn`) takes time to catch up — it may still be serving observations that are many hours old even though the hub is actively broadcasting fresh data over UDP on the local network.

**What happened:**

- The plugin's staleness gate in `_on_web_obs` compared the cloud observation timestamp against the current time
- It found data that was, say, 23 hours old and correctly identified it as stale
- It turned the device red with **"Stale data"** even though the hub was fully online and streaming fresh UDP data locally
- The device would stay red until the cloud pipeline fully caught up, which could take hours

**Fix:** Before marking a device stale or offline, the plugin now checks whether local UDP data has been received from that serial number within the last 5 minutes. If UDP is active, the cloud observation is silently skipped — the device stays green, and the cloud lag is allowed to resolve on its own. A debug log is written explaining the bypass:

```
WeatherFlow Tempest: web data is 1412 min old but UDP active (last 45 s ago)
— skipping web update, not marking stale
```

This check applies only to personal Tempest devices. Web-only devices (no UDP path) continue to use the cloud timestamp for all staleness decisions.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required.
- If you see a **"serial not found via UDP"** warning (Fix 1), edit the Indigo device and update the serial number to the active sensor shown in the message.
- Web-only devices and Public Tempest Station devices are not affected by either change.
