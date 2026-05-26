<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.5.3

**Released:** 2026-05-26
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

Fix for "state key not defined" errors that appeared in the Indigo log when a Tempest device recovered from offline, or when strike / lightning events fired after a reconnection.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Changes

### Dynamic State Registration on Write

**Problem:** Indigo logged repeated errors of the form:

```
Error: device "Tempest Weather" state key last_strike_formatted not defined
Error: device "Tempest Weather" state key strike_distance not defined
Error: device "Tempest Weather" state key strike_energy not defined
```

These appeared in pairs immediately after a web observation update, triggered when a device came back online after a flat-battery offline period.

**Cause:** The plugin creates certain device states dynamically — strike distance, strike energy, and related states are only registered the first time the relevant UDP event is received. When a device is offline at startup (or for an extended period), those events never fire, so the states are never registered on the device. When the web poller then resumes and tries to write those keys, Indigo rejects them as undefined.

A secondary cause: the 2.5.2 recovery path called `stateListOrDisplayStateIdChanged()` unconditionally whenever a station recovered. This forced Indigo to validate the device's entire state list, which generated "not defined" log entries for every legacy state name present in the device's database from older plugin versions — even though nothing was trying to write those states.

**Fix — `_safe_update_states` helper:** All state write calls now go through a single helper that:

1. Checks whether every key about to be written is present in `dev.states`.
2. If any are missing, calls `stateListOrDisplayStateIdChanged()` to re-read Devices.xml and register newly-defined states.
3. Re-fetches the device object so `dev.states` is current.
4. Filters out any keys that are **still** absent after the sync — these are legacy state names from older plugin versions that no longer exist in Devices.xml. They are silently skipped with a Debug log entry instead of an Indigo Error.
5. Writes the clean, validated state list.

The `stateListOrDisplayStateIdChanged()` call in the offline-recovery path has been removed. State-list reconciliation now happens lazily — only when a specific missing key is detected, not proactively on every recovery event.

**Scope:** All state update paths use the helper: UDP observation, status update, rapid wind, lightning strike, hub status, web observation, and public station observation.

**Log output when a missing key is detected and registered (normal case):**
```
Debug: Tempest Weather: state keys not yet registered ['last_strike_distance', 'last_strike_energy'] — refreshing state list
```

After this log, `stateListOrDisplayStateIdChanged()` re-reads Devices.xml, the keys are registered, and the states are written normally. No data is lost.

**Log output when a key is filtered out:**
```
Debug: Tempest Weather: skipping 1 legacy/undefined state(s): ['old_removed_key']
```

This only fires for state keys that are **not in Devices.xml at all** — i.e., state names that have been completely removed from the plugin in a prior version, but whose names remain stored in an old device's Indigo database. If the plugin is actively writing a key, it is defined in Devices.xml and will be registered by `stateListOrDisplayStateIdChanged()`, not skipped.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required. The fix is automatic.
- Existing devices do not need to be deleted or recreated. Legacy state names left over from older plugin versions are silently filtered on first write and do not cause errors.
- Reload the plugin after updating.
