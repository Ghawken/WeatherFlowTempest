<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# WeatherFlow Tempest Weather Station — Indigo Plugin

Receives live weather data from [WeatherFlow Tempest](https://weatherflow.com/tempest-weather-system/) stations via **local UDP broadcast** and maps all sensor observations to Indigo device states. No cloud account is required for basic operation. An optional **WeatherFlow Web API** token unlocks authoritative rain totals, rain duration, conditions text, hourly lightning counts, and a **web-only mode** that works even when the hub is on a different network.

See Wiki: https://github.com/Ghawken/WeatherFlowTempest/wiki

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Screenshot

![WeatherFlow Device States](https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/WeatherFlowStates.png)

*Indigo device states for a Tempest Weather Station showing live sensor readings, web-sourced rain totals, and unit labels.*

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Features

| Category | What you get |
|---|---|
| **Temperature** | Ambient, feels-like, dew point, wet bulb, wind chill, heat index, delta-T |
| **Atmospheric** | Station pressure, sea-level pressure, relative humidity, vapour pressure, air density |
| **Wind** | Instantaneous speed/direction (rapid-wind, ~3 s), 1-minute average, gust, lull, cardinal, sample interval |
| **Rain** | Per-minute accumulation, rain rate, intensity label, daily total, yesterday's total, Rain Check status |
| **Rain (web)** | Authoritative rain-check-corrected totals, last-1-hour rain, daily/yesterday rain duration in minutes |
| **Lightning** | Strike count, average distance, last-strike distance, energy and timestamp |
| **Lightning (web)** | Hourly and 3-hour strike counts |
| **Conditions (web)** | Weather conditions text and icon name from WeatherFlow forecast engine |
| **Light** | Illuminance (lux), solar radiation (W/m²), UV index |
| **Battery** | Voltage and percentage; power-save mode label; report interval |
| **Derived** | Cloud base, freezing level (both require altitude to be set) |
| **Diagnostics** | RSSI, firmware version, sensor fault flags, silence detection |
| **Hub** | Firmware, Wi-Fi RSSI, uptime, reset reasons |

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Navigation

| Page | Contents |
|---|---|
| [[Installation]] | Requirements and install steps |
| [[Plugin-Configuration]] | UDP port, Web API token, log levels, device auto-generation |
| [[Web-API]] | Web API setup, web-only mode, extra states |
| [[Tempest-Device-Configuration]] | Unit selection, altitude, device picker, web-only mode |
| [[Device-States]] | Every state — what it means, units, notes |
| [[Triggers]] | Lightning, rain-start, and rapid-wind triggers |
| [[Rain-Data]] | How daily rain is sourced and why power-save mode matters |
| [[Troubleshooting]] | Common problems and fixes |
| [[Architecture]] | Internal design: UDP → asyncio → Indigo |

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Requirements

| Requirement | Version |
|---|---|
| Indigo | 2025.2 or later (ServerApiVersion 3.4) |
| WeatherFlow hub | Any — must be on the same subnet as the Indigo Mac (or use web-only mode) |

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Quick Start

1. Install the plugin (double-click `WeatherFlowTempest.indigoPlugin`).
2. Go to **Plugins → WeatherFlow Tempest → Configure → Generate Devices**.
3. Done — states populate within 60 seconds of the first UDP broadcast.

For web API features, see [Plugin Configuration](#plugin-configuration) below.

See [[Installation]] for full details.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Plugin Configuration

Open **Plugins → WeatherFlow Tempest Weather Station → Configure**.

![Plugin Configuration](https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/pluginConfig.png)

### Device Generation

Click **Generate Devices** to auto-create Indigo devices for every Tempest and Hub currently broadcasting on the network. Re-press whenever new hardware is added.

### UDP Listener Settings

| Setting | Description |
|---|---|
| **UDP Port** | Port the hub broadcasts on (default: `50222`) |
| **Listen Address** | Network interface to listen on (default: `0.0.0.0` = all interfaces) |

Saving the preferences automatically restarts the UDP listener.

### WeatherFlow Web API (Optional)

| Setting | Description |
|---|---|
| **Enable Web API** | Tick to activate web-based data polling |
| **API Token** | Your Personal Use Token from [tempestwx.com → Settings → Data Authorizations](https://tempestwx.com/settings/tokens) |

When enabled the plugin polls the WeatherFlow REST API to supplement UDP data with:

- **Authoritative rain totals** — rain-check corrected daily and yesterday rain
- **Rain last 1 hour** — rolling 1-hour rainfall total
- **Rain duration** — minutes of measurable rain today and yesterday
- **Conditions & icon** — current weather description and icon name from WeatherFlow's forecast engine
- **Hourly lightning counts** — strikes in the last 1 hour and last 3 hours

The web API is polled every **5 minutes** when UDP data is active (slow-changing supplemental data only), or every **60 seconds** in web-only mode (all states come from web).

> **Getting a token:** Log in to [tempestwx.com](https://tempestwx.com), go to **Settings → Data Authorizations**, and generate a Personal Use Token. It is free and tied to your WeatherFlow account.

> **Note:** The WeatherFlow REST API authenticates by account — it only serves stations registered to the token's owner. There is no unauthenticated public access through the REST API.

### Debugging Options

| Setting | Description |
|---|---|
| **Indigo Log Level** | Verbosity of messages in the Indigo Event Log |
| **File Log Level** | Verbosity of messages written to the plugin log file |

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Device Setup

### Auto-create all devices at once (recommended)

1. Open **Plugins → WeatherFlow Tempest Weather Station → Configure**.
2. Click **Generate Devices**.
3. The plugin creates one Indigo device for every Tempest and Hub currently broadcasting on the network. Devices are placed in the main Indigo device folder and can be moved afterward.
4. Re-click the button whenever new hardware is added.

### Manual device creation

1. Go to **Devices → New Device → Type: WeatherFlow Tempest Weather Station**.
2. Choose **Tempest Weather Station** or **WeatherFlow Hub**.
3. Select your unit from the dropdown — devices are listed as soon as the hub broadcasts.
4. Click **Save**.

> **Tip:** If the device dropdown is empty, the hub has not yet sent a broadcast. Wait 30–60 seconds and use the **Reload** button in the dialog to refresh the list.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Tempest Device Configuration

![Device Configuration](https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/deviceConfig.png)

| Field | Description |
|---|---|
| **Tempest Device** | Serial number of the Tempest (ST-xxxxxxxx), discovered automatically from UDP |
| **Web-only (hub on different network)** | Tick to bypass UDP and use the web API exclusively — see below |
| **Altitude (m)** | Station elevation in metres above sea level. Used to calculate sea-level pressure, cloud base, and freezing level. Set to `0` to omit those derived states. |
| **Temperature** | °C or °F |
| **Pressure** | hPa (mbar), mmHg, or inHg |
| **Wind Speed** | m/s, km/h, mph, or knots |
| **Rainfall** | mm or inches |
| **Altitude unit** | Metres or feet (for cloud base and freezing level) |

Unit selections are independent — mix and match as needed. Changes take effect on the next sensor observation. Active unit labels are stored in the `unit_temperature`, `unit_pressure`, `unit_wind`, and `unit_rain` device states.

### Web-only Mode

Enable **Web-only (hub on different network)** when the Tempest hub is on a separate network from the Indigo Mac (e.g. a remote property, a neighbour's setup with shared access, or a different VLAN where UDP broadcast doesn't reach).

When web-only is ticked, one additional field appears:

| Field | Description |
|---|---|
| **Station ID** | Numeric WeatherFlow station ID — found in the WeatherFlow app under station Settings |

The Web API must be enabled and a valid token entered in Plugin Preferences. The device is polled every 60 seconds and all sensor states (temperature, pressure, wind, rain, UV, lightning, conditions) are populated from the web. The `deviceStatus` state shows **Active (web)** when data is flowing.

> **Station ID:** Open the WeatherFlow app, tap your station name, then tap **Settings**. The station ID is the number shown in the Station Information section.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Device States

### Tempest Weather Station

#### Temperature
| State | Description |
|---|---|
| `air_temperature` | Ambient temperature |
| `temperature` | Alias for `air_temperature` |
| `feels_like_temperature` | Apparent / feels-like temperature |
| `dew_point_temperature` | Dew point |
| `wet_bulb_temperature` | Wet bulb temperature |
| `wind_chill_temperature` | Wind chill |
| `heat_index` | Heat index |
| `delta_t` | Delta-T (dry bulb minus wet bulb) |

#### Atmospheric
| State | Description |
|---|---|
| `relative_humidity` | Relative humidity (%) |
| `station_pressure` | Raw station pressure |
| `sea_level_pressure` | Sea-level corrected pressure (requires altitude > 0) |
| `vapor_pressure` | Vapour pressure |
| `air_density` | Air density (kg/m³, always metric) |

#### Derived (require altitude > 0)
| State | Description |
|---|---|
| `cloud_base` | Estimated cloud base height above station |
| `freezing_level` | Estimated freezing level height above station |

#### Light & UV
| State | Description |
|---|---|
| `illuminance` | Illuminance (lux) |
| `solar_radiation` | Solar irradiance (W/m²) |
| `uv` | UV index |

#### Rain
| State | Source | Description |
|---|---|---|
| `rain_accumulation_previous_minute` | UDP | Rain accumulated in the previous minute |
| `rain_rate` | UDP | Current rain rate (mm/h or in/h) |
| `rain_intensity` | UDP | None / Very Light / Light / Moderate / Heavy / Violent |
| `rain_today` | UDP + Web | Total rain since local midnight (web value is rain-check corrected) |
| `rain_yesterday` | UDP + Web | Yesterday's total rain |
| `rain_check` | UDP | WeatherFlow Rain Check verification status (`none` / `on` / `off`) |
| `precipitation_type` | UDP | `none`, `rain`, `hail`, or `rain_hail` |
| `last_rain_start` | UDP | Timestamp of the most recent rain-start event (UTC) |
| `rain_last_1hr` | **Web only** | Rain accumulated in the last 60 minutes |
| `rain_duration_today` | **Web only** | Minutes of measurable rain today |
| `rain_duration_yesterday` | **Web only** | Minutes of measurable rain yesterday |

#### Lightning
| State | Source | Description |
|---|---|---|
| `lightning_strike_count` | UDP | Strikes detected in the last 3 minutes |
| `lightning_strike_average_distance` | UDP | Average distance of recent strikes |
| `last_strike_distance` | UDP | Distance of the most recent strike |
| `last_strike_energy` | UDP | Energy of the most recent strike |
| `last_strike_time` | UDP | Timestamp of the most recent strike (UTC) |
| `lightning_count_last_1hr` | **Web only** | Strikes in the last 60 minutes |
| `lightning_count_last_3hr` | **Web only** | Strikes in the last 3 hours |

#### Conditions (Web API only)
| State | Description |
|---|---|
| `conditions` | Current weather description (e.g. "Partly Cloudy") |
| `weather_icon` | Icon name from WeatherFlow's forecast engine (e.g. `partly-cloudy-day`) |

#### Wind
| State | Description |
|---|---|
| `wind_speed` | Instantaneous wind speed (rapid-wind, ~3 s interval) |
| `wind_average` | 1-minute average wind speed |
| `wind_gust` | 1-minute wind gust |
| `wind_lull` | 1-minute wind lull |
| `wind_direction` | Instantaneous wind direction (°) |
| `wind_direction_average` | 1-minute average wind direction (°) |
| `wind_direction_cardinal` | Instantaneous cardinal direction (N, NE, …) |
| `wind_direction_average_cardinal` | Average cardinal direction |
| `wind_sample_interval` | Wind measurement window (seconds) |

#### Unit labels
| State | Description |
|---|---|
| `unit_temperature` | Active temperature unit label (e.g. `°C`) |
| `unit_pressure` | Active pressure unit label (e.g. `hPa`) |
| `unit_wind` | Active wind speed unit label (e.g. `km/h`) |
| `unit_rain` | Active rain unit label (e.g. `mm`) |

#### Battery & power
| State | Description |
|---|---|
| `battery` | Battery voltage (V) |
| `battery_percent` | Battery level (%) |
| `power_save_mode` | Active power-save mode name |
| `report_interval` | Observation reporting frequency (minutes) |

#### Diagnostics
| State | Description |
|---|---|
| `rssi` | Tempest RF signal strength (dBm) |
| `hub_rssi` | Hub RF signal strength (dBm) |
| `firmware_revision` | Tempest firmware version |
| `hub_sn` | Hub serial number |
| `up_since` | Device power-on timestamp (UTC) |
| `last_report` | Timestamp of the most recent observation (UTC) |
| `sensor_status` | Sensor fault flags, or `OK` |
| `deviceStatus` | `Active` (UDP), `Active (web)` (web-only), `Waiting for data` on startup, `No data — last seen N min ago` if silent |

---

### WeatherFlow Hub

| State | Description |
|---|---|
| `firmware_revision` | Hub firmware version |
| `rssi` | Hub Wi-Fi signal strength (dBm) |
| `up_since` | Hub power-on timestamp (UTC) |
| `uptime` | Seconds since last boot |
| `reset_flags` | Reason(s) for the last reset (comma-separated) |
| `deviceStatus` | Connection status |

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

# Triggers

Three custom trigger types are available under **Triggers → New Trigger → WeatherFlow Tempest Weather Station**.

Each trigger includes a **Tempest Device** picker so it can be scoped to a specific station when you have more than one.

## Lightning Strike Detected

Fires whenever the selected Tempest detects a lightning strike.

| Field | Description |
|---|---|
| **Tempest Device** | The Tempest station to watch. Leave blank to fire for any station. |

The `last_strike_distance`, `last_strike_energy`, and `last_strike_time` device states are updated before the trigger fires.

**Use cases:** push notification with distance and energy; flash a light; log strikes to a variable.

## Rain Started

Fires when the Tempest detects the onset of precipitation (the first rain-start event after a dry period).

> **Note:** This trigger fires from the Tempest's dedicated rain-start event, which is sent immediately when the sensor detects rain — independent of the 1-minute observation cycle. It fires once per rain onset, not repeatedly while rain continues.

The `last_rain_start` device state is updated when this trigger fires.

**Use cases:** close roof vents; retract a pergola awning; send a notification.

## Rapid Wind Exceeds Threshold

Fires when an instantaneous wind reading meets or exceeds a configurable speed. Rapid-wind readings arrive approximately **every 3 seconds**.

| Field | Description |
|---|---|
| **Tempest Device** | The Tempest station to watch. |
| **Threshold (m/s)** | Minimum wind speed (in m/s) required to fire the trigger. |

> The threshold is always compared against the **raw m/s magnitude** regardless of the display unit. Convert if needed: 1 m/s = 3.6 km/h = 2.237 mph = 1.944 kn.

**Use cases:** close greenhouse vents above 10 m/s; retract a sail shade above 15 m/s.

## Trigger Limitations

- In power-save **MODE_2** and above, rapid-wind events are not sent by the Tempest. The *Rapid Wind Exceeds Threshold* trigger will not fire in those modes.
- Lightning and rain-start triggers fire from discrete UDP events and are not affected by power-save mode.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Station Silence Detection

The plugin monitors each Tempest station for data dropouts. If no observation is received for more than **5 minutes**:

- The `deviceStatus` state is updated to `"No data — last seen N min ago"`.
- A warning is written to the Indigo Event Log.
- The warning repeats every **30 minutes** with an updated elapsed time.

When data resumes, `deviceStatus` returns to `"Active"` automatically and a recovery notice is logged.

The plugin also monitors the UDP listener itself — if the background socket task crashes, the listener is restarted automatically within 60 seconds. The web API poller is similarly monitored and restarted if it exits unexpectedly.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Plugin Menu

**Plugins → WeatherFlow Tempest Weather Station** exposes two menu commands:

- **List Discovered WeatherFlow Devices** — logs all currently-discovered serial numbers, models, and firmware versions to the Event Log.
- **Restart UDP Listener** — stops and restarts the listener without reloading the plugin (useful after network changes).

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Troubleshooting

**Device dropdown is empty / "No devices discovered yet"**
- Confirm the WeatherFlow hub is on the same subnet as the Indigo Mac. UDP broadcast does not cross router boundaries.
- Check that nothing is blocking UDP port 50222 (macOS firewall, managed switch, VLAN separation).
- Wait 60 seconds — hubs broadcast a status packet roughly once per minute — then use the **Reload** button in the device dialog.
- If the hub is on a different network, use **Web-only mode** in the device configuration instead.

**`deviceStatus` shows "No data — last seen N min ago"**
- The station has not sent an observation in over 5 minutes. Check the hub's power and Wi-Fi connection, and confirm the Tempest is within RF range.
- Use **Plugins → WeatherFlow → Restart UDP Listener** to retry without reloading the plugin.

**Web API returns 401 Unauthorized**
- Verify the API token is correct in Plugin Preferences (Plugins → Configure).
- Ensure the Station ID in the device config matches a station registered to the token's account. Find your station ID in the WeatherFlow app under station Settings.
- After 3 consecutive 401 errors for a station, polling is suspended. Correct the station ID and save the device to resume.

**`rain_last_1hr`, `conditions`, `weather_icon` are always empty**
- These states require the Web API to be enabled. Tick **Enable Web API** in Plugin Preferences and enter a valid token.

**`sea_level_pressure`, `cloud_base`, `freezing_level` are missing**
- Set **Altitude (m)** to a non-zero value in the Tempest device configuration.

**`sensor_status` shows all sensors failed**
- This is a known firmware quirk (seen in firmware 181) where the hardware register is read before sensor self-test completes. The plugin detects this pattern and displays `OK` instead. A subset of sensors listed as failed is a genuine fault.

**Debug logging**
- Set **Indigo Log Level** to *Debugging Messages* in Plugin Preferences for verbose output.
- The plugin log file is at `~/Library/Application Support/Perceptive Automation/Indigo 2025.x/Logs/`. Set **File Log Level** to *Detailed Debugging Messages* for maximum detail.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Libraries & Acknowledgements

### [pyweatherflowudp](https://github.com/natekspencer/pyweatherflowudp) — v1.5.2
*by Nathan Spencer ([@natekspencer](https://github.com/natekspencer))*

The core UDP library that handles all communication with the WeatherFlow hub. Provides an event-based async interface, parses every WeatherFlow message type, and exposes sensor values as typed properties with full unit support. All derived meteorological calculations (dew point, wet bulb, heat index, feels-like, vapour pressure, air density, sea-level pressure, cloud base, freezing level) are provided by this library.

Licensed under MIT. Consider [supporting Nathan on Ko-fi](https://ko-fi.com/natekspencer).

### [Pint](https://pint.readthedocs.io/) — v0.25.3
Physical quantity handling with units. All sensor values carry their native unit and are converted to the user's chosen display unit using Pint's unit registry.

### [PsychroLib](https://github.com/psychrometrics/psychrolib) — v2.5.0
Psychrometric calculations used by pyweatherflowudp to derive wet bulb temperature and related humidity metrics.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## License

MIT — see [LICENSE](LICENSE) for details.

Developed by GlennNZ.
