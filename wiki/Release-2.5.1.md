<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.5.1

**Released:** 2026-05-24
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

This is a bug-fix release addressing three issues: stale web data being written to device states when a station goes offline, Indigo state errors on older Air and Sky devices, and duplicate polling on plugin startup.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Bug Fixes

### Web Backup No Longer Updates States with Stale Data

**Problem:** When UDP communication to a local Tempest went down, the web backup poller would take over and push all sensor states from the WeatherFlow cloud API. If the station itself was also offline, WeatherFlow's API returns its last cached observation indefinitely — meaning the plugin would keep writing hour-old (or older) temperature, wind, pressure, and rain values to Indigo device states on every poll cycle.

The same issue affected Public Tempest Station devices: if a public station went offline, its last cached data would keep refreshing in Indigo as though it were live.

**Fix:** Both the personal web API poller and the public station poller now check the age of the observation timestamp before committing any states:

- **Personal stations** — `current_conditions.time` from the `better_forecast` endpoint is the actual observation timestamp (confirmed from WeatherFlow's own REST API library). If the observation is more than **10 minutes old**, the update is skipped entirely.
- **Public stations** — `obs[0].timestamp` from the `/observations/station/{id}` endpoint. Same 10-minute threshold.

When data is rejected, a warning is written to the Indigo log:

```
My Tempest: web observation is 47.2 min old (obs_time=1748030400) — skipping update
My Public Station: public observation is 23.8 min old (timestamp=1748031600) — skipping update
```

### Observation Age Now Logged at Debug Level

On every successful web poll, the observation age is now written to the plugin log at **Debug** level. This makes it straightforward to confirm data freshness and to spot a station going stale before it crosses the rejection threshold:

```
My Tempest: web observation age 3 s (0.1 min)
My Public Station: public observation age 47 s (0.8 min)
```

### Air Device State Errors Fixed

**Problem:** Users with older WeatherFlow Air (AR-) devices saw a stream of Indigo state errors on every observation:

```
Error device "WeatherFlow Air AR-XXXXXXXX" state key rain_intensity not defined (ignoring update request)
Error device "WeatherFlow Air AR-XXXXXXXX" state key rain_today not defined (ignoring update request)
Error device "WeatherFlow Air AR-XXXXXXXX" state key rain_today_raw_mm not defined (ignoring update request)
Error device "WeatherFlow Air AR-XXXXXXXX" state key rain_today_date not defined (ignoring update request)
```

The Air sensor has no rain hardware, so its device type does not define rain states. However the observation state builder was writing rain states unconditionally for all device types. A secondary issue caused the daily rain accumulator to compute a spurious `0.0 mm` value for Air (because both rain properties return `None`, summing to `0.0`), which passed a `not None` check and attempted to write `rain_today` and `rain_today_raw_mm`.

**Fix:** All rain-related states (`rain_intensity`, `rain_today`, `rain_today_raw_mm`, `rain_today_date`, `rain_yesterday`, `rain_rate`, `rain_accumulation_previous_minute`, `precipitation_type`) are now guarded by a `SkySensorType` check. Sky and Tempest devices both satisfy this check and are unaffected. The daily rain accumulation calculation is also skipped entirely for Air, so no spurious `0.0` value is computed.

### Duplicate Polling on Startup Fixed

**Problem:** On plugin startup, the public station poller and web API poller could each spawn two concurrent polling tasks, resulting in every API call and every log line being doubled:

**Fix:** A second guard check was added *inside* the scheduled callback, which runs on the event loop and is therefore strictly serial. By the time the second callback executes, the first has already assigned the task, so the duplicate creation is suppressed. The same fix was applied to the web API poller. The "poller started" log message was also moved inside the callback so it only appears when a task is actually created.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- No configuration changes required. All fixes are automatic for existing devices.
- The 10-minute staleness threshold is intentionally conservative — a healthy station updates every 60 seconds, so any age above 10 minutes indicates the station or its cloud connection is genuinely offline.
- Air (AR-) and Sky (SK-) device users should reload the plugin after updating to clear any accumulated state errors from prior versions.
