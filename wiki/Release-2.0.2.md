<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Release 2.0.2

**Released:** 2026-05-23
**Minimum Indigo version:** 2025.2

← [Back to Changelog](https://github.com/Ghawken/WeatherFlowTempest/wiki/Changelog)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Highlights

This release adds an optional **WeatherFlow Web API** integration that unlocks nine new device states unavailable from UDP, including rain-check corrected totals, rolling rain and lightning counts, and current weather conditions. It also introduces **web-only mode** — a way to monitor a Tempest hub on a different network by sourcing all data from the cloud API.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## New Features

### WeatherFlow Web API (Optional)

Enable in **Plugin Preferences → Enable Web API** with a free Personal Use Token from your WeatherFlow account. When active, the plugin polls the WeatherFlow REST API every 5 minutes to supplement local UDP data.

Nine new device states are added:

| State | Source | Description |
|---|---|---|
| `rain_today` | Web API | Authoritative daily total — rain-check corrected by WeatherFlow servers |
| `rain_yesterday` | Web API | Authoritative yesterday total, rain-check corrected |
| `rain_last_1hr` | Web API | Rolling 60-minute rainfall total |
| `rain_duration_today` | Web API | Minutes of measurable rain today |
| `rain_duration_yesterday` | Web API | Minutes of measurable rain yesterday |
| `conditions` | Web API | Current weather description, e.g. "Partly Cloudy" |
| `weather_icon` | Web API | Icon name from WeatherFlow's forecast engine |
| `lightning_count_last_1hr` | Web API | Strikes in the last 60 minutes |
| `lightning_count_last_3hr` | Web API | Strikes in the last 3 hours |

When UDP and the Web API are both active, real-time sensor readings (temperature, wind, pressure, etc.) continue to come from UDP. Web API updates rain totals and provides the web-exclusive states above.

### Web-only Mode

Devices can now be configured for **web-only mode** — tick **Web-only (hub on different network)** in the device configuration and enter your Station ID. Use this when:

- The Tempest hub is on a different network, subnet, or VLAN from the Indigo Mac
- UDP broadcast cannot reach the Indigo Mac
- You want a fully cloud-sourced device with no dependency on local networking

In web-only mode, all sensor readings come from the REST API, polled every **60 seconds**. `deviceStatus` displays **Active (web)** when data is flowing.

Web-only devices require only a **Station ID** — no serial number entry is needed.

### Automatic UDP Fallback

If a UDP station goes silent for more than 5 minutes, the web API automatically provides all standard sensor readings (including temperature, wind, pressure, etc.) until UDP resumes. This ensures states remain current even during temporary network interruptions.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Improvements

- **Plugin Preferences** now includes a Web API section with enable toggle and API token field
- **Device configuration** simplified — web-only devices no longer require a serial number to be entered manually
- **Web poller auto-restart**: `runConcurrentThread` detects if the web poll task exits unexpectedly and restarts it automatically
- **Consecutive failure tracking**: the web poller warns after 1–2 consecutive failures per station and silently suspends polling after 3. Edit and save the device to reset the counter and resume
- **Wind direction** stored as cardinal abbreviation (N, NNE, NE … NNW) via an internal `_degrees_to_cardinal` helper
- **Plugin Menu**: new **List Discovered WeatherFlow Devices** item — logs all currently-discovered serial numbers, models, and firmware versions to the Event Log

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Documentation

- New wiki pages: [Plugin Configuration](https://github.com/Ghawken/WeatherFlowTempest/wiki/Plugin-Configuration), [Tempest Device Configuration](https://github.com/Ghawken/WeatherFlowTempest/wiki/Tempest-Device-Configuration), [Web API](https://github.com/Ghawken/WeatherFlowTempest/wiki/Web-API)
- GitHub Actions workflow to automatically sync `wiki/` from the main repo to the GitHub wiki on every push
- README.md updated with new device states, configuration screenshots, and full wiki links
- README.bbcode updated for the Indigo plugin forum

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Upgrade Notes

- The Web API is **opt-in** — the plugin continues to work without it. No configuration changes are needed for existing UDP-only setups.
- To enable the Web API, get a free Personal Use Token from [tempestwx.com → Settings → Data Authorizations](https://tempestwx.com/settings/tokens) and enter it in Plugin Preferences.
- A 401 Unauthorized error from the web API means either the token is invalid or the Station ID belongs to a different account. The WeatherFlow REST API only serves stations registered to the token's account.
