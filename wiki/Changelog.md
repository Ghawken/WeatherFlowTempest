<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Changelog

All notable changes to the WeatherFlow Tempest plugin are listed here. Each release links to a dedicated page with full details.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Releases

| Version | Date | Summary |
|---|---|---|
| [**2.5.8**](https://github.com/Ghawken/WeatherFlowTempest/wiki/Release-2.5.8) | 2026-06-08 | Fix Public Tempest Station ignoring unit preferences (always showed metric); fix `last_strike_distance` / `last_strike_time` not updating during thunderstorms; promote strike log to INFO; add Distance Display (km/mi) to Tempest/Sky/Air ConfigUI |
| [**2.5.7**](https://github.com/Ghawken/WeatherFlowTempest/wiki/Release-2.5.7) | 2026-06-04 | Fix Conditions menu still showing hardcoded metric units (e.g. "Air Temp °C") — completes the unit-label cleanup from 2.5.6 |
| [**2.5.6**](https://github.com/Ghawken/WeatherFlowTempest/wiki/Release-2.5.6) | 2026-06-03 | Heat index and wind chill show blank (not `0`) when conditions are not met; trigger/condition menus no longer show hardcoded metric unit labels |
| [**2.5.5**](https://github.com/Ghawken/WeatherFlowTempest/wiki/Release-2.5.5) | 2026-05-31 | Fix `delta_t` and `heat_index` ignoring temperature unit preference — both now correctly display Δ°F / °F when device is set to Fahrenheit |
| [**2.5.4**](https://github.com/Ghawken/WeatherFlowTempest/wiki/Release-2.5.4) | 2026-05-30 | Separate local and web rain accumulation — four new states (`rain_today_local`, `rain_today_local_raw_mm`, `rain_yesterday_local`, `rain_today_source`); fixes fallback accumulation corruption and midnight-rollover inconsistency |
| [**2.5.3**](https://github.com/Ghawken/WeatherFlowTempest/wiki/Release-2.5.3) | 2026-05-26 | Fix "state key not defined" errors for dynamically-created states; safe state write helper registers missing keys before writing, filters legacy orphaned states |
| [**2.5.2**](https://github.com/Ghawken/WeatherFlowTempest/wiki/Release-2.5.2) | 2026-05-26 | Personal station offline detection rewritten using `/observations/stn`; device turns red in UI after 10 min stale, marked Offline after 30 min |
| [**2.5.1**](https://github.com/Ghawken/WeatherFlowTempest/wiki/Release-2.5.1) | 2026-05-24 | Bug fixes — stale web data rejected after 10 minutes, Air device rain state errors resolved, duplicate polling on startup fixed |
| [**2.5.0**](https://github.com/Ghawken/WeatherFlowTempest/wiki/Release-2.5.0) | 2026-05-23 | Public Tempest Station device type — monitor any public WeatherFlow station, distance and direction states, unlimited stations for a weather network |
| [**2.0.2**](https://github.com/Ghawken/WeatherFlowTempest/wiki/Release-2.0.2) | 2026-05-23 | WeatherFlow Web API integration, web-only mode for remote hubs, nine new device states, comprehensive wiki documentation |

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

> New releases will be added to the top of this table.
