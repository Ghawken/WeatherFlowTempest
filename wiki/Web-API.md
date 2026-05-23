# WeatherFlow Web API

The WeatherFlow Web API is an **optional** feature that supplements the local UDP data with cloud-sourced information. It requires a free Personal Use Token from your WeatherFlow account.


---

## What the Web API adds

| State | Notes |
|---|---|
| `rain_today` | Authoritative daily total — rain-check corrected by WeatherFlow servers. Replaces the UDP-accumulated value. |
| `rain_yesterday` | Authoritative yesterday total, rain-check corrected. |
| `rain_last_1hr` | Rolling 60-minute rainfall total. Not available from UDP. |
| `rain_duration_today` | Minutes of measurable rain today. Not available from UDP. |
| `rain_duration_yesterday` | Minutes of measurable rain yesterday. Not available from UDP. |
| `conditions` | Current weather description, e.g. "Partly Cloudy". Not available from UDP. |
| `weather_icon` | Icon name from WeatherFlow's forecast engine. Not available from UDP. |
| `lightning_count_last_1hr` | Strikes in the last 60 minutes. Not available from UDP. |
| `lightning_count_last_3hr` | Strikes in the last 3 hours. Not available from UDP. |

When the Web API is active alongside UDP, real-time sensor readings (temperature, pressure, wind, UV, etc.) continue to come from UDP. The web API only updates rain totals and the web-exclusive states above, polled every **5 minutes**.

In **web-only mode**, all states including real-time sensor readings come from the web API, polled every **60 seconds**.

---

## Setup

### 1. Get a Personal Use Token

1. Log in to [tempestwx.com](https://tempestwx.com).
2. Go to **Settings → Data Authorizations**.
3. Click **Generate Token** and copy the token string.

The token is free and tied to your WeatherFlow account.

> **Note:** The WeatherFlow REST API authenticates by account. It only serves stations registered to your token — there is no unauthenticated public access through the API.

### 2. Enable in Plugin Preferences

Open **Plugins → WeatherFlow Tempest Weather Station → Configure**.

![Plugin Configuration](https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/pluginConfig.png)

1. Tick **Enable Web API**.
2. Paste your token into the **API Token** field.
3. Click **Save**. The web poller starts automatically.

---

## Poll intervals

| Mode | Interval | Reason |
|---|---|---|
| UDP active (web supplements) | 5 minutes | Rain totals and conditions are slow-changing; UDP handles real-time data |
| Web-only (no local hub) | 60 seconds | All sensor states come from the web — faster polling needed |

The plugin selects the interval automatically based on whether any device is in web-only mode.

---

## Web-only Mode

Use this when the WeatherFlow hub is on a different network from the Indigo Mac — for example, a remote property, a separate VLAN, or any location where UDP broadcast cannot reach Indigo.

### How to configure

1. Open the Tempest device configuration (double-click the device in Indigo).
2. Tick **Web-only (hub on different network)**.
3. Enter your **Station ID** (found in the WeatherFlow app under station Settings).
4. Ensure the Web API is enabled with a valid token in Plugin Preferences.
5. Click **Save**.

![Device Configuration](https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/deviceConfig.png)

The device status changes to **Active (web)** once the first poll succeeds. All sensor states populate from the web within 60 seconds.

### Finding your Station ID

Open the WeatherFlow app, tap your station name, then tap **Settings**. The Station ID is the number shown in the Station Information section. It is also visible in the URL when you view your station on tempestwx.com — e.g. `tempestwx.com/station/`**183063**.

---

## Error handling

The plugin tracks consecutive failures per station:

| Failures | Behaviour |
|---|---|
| 1–2 | Warning logged: station ID and error message |
| 3 | Final warning logged; polling suspended silently |
| After fix | Edit the device and save to reset the counter and resume polling |

A 401 Unauthorized error means either the token is invalid or the Station ID does not belong to the token's account. Check both in Plugin Preferences and the device configuration.

---

## Interaction with UDP data

When both UDP and the Web API are active for the same device:

- **UDP wins for real-time readings**: temperature, pressure, wind, humidity, UV, battery, and per-minute rain are always written by UDP when it is active.
- **Web wins for rain totals**: `rain_today` and `rain_yesterday` are always overwritten by the web API because the web values are rain-check corrected by WeatherFlow's servers — more accurate than the plugin's local accumulation from UDP.
- **Web-exclusive states** (`rain_last_1hr`, `conditions`, `weather_icon`, etc.) are only available from the web API.

If the local UDP station goes silent for more than 5 minutes, the web API automatically takes over all states (switches to `include_standard=True`) until UDP resumes.
