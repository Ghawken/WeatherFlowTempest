<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Public Tempest Station

The **Public Tempest Station** device type lets you monitor any publicly-shared WeatherFlow station on [tempestwx.com](https://tempestwx.com) — no personal API token and no WeatherFlow account required. All you need is the station's numeric ID from its URL.

This makes it possible to build a network of weather reference points surrounding your Indigo location: a neighbour's rooftop station to the north, a coastal station to the west, an inland station tracking temperature inversions. Each device polls independently every 120 seconds and surfaces the same rich weather dataset as a local Tempest, plus direction and distance states that tell you exactly where each station sits relative to your Indigo server.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Finding a Station ID

Every public WeatherFlow station has a URL of the form:

```
https://tempestwx.com/station/130809/
```

The number in the URL — `130809` in this example — is the station ID. You can browse the [WeatherFlow map](https://tempestwx.com) to find stations near you; clicking a station marker opens its page and reveals its ID in the address bar.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Device Setup

1. Go to **Devices → New Device**.
2. Set **Type** to **WeatherFlow Tempest Weather Station**.
3. Choose **Public Tempest Station** from the model list.
4. Enter the **Station ID** from the station's tempestwx.com URL.
5. Select your preferred display units (temperature, pressure, wind, rain, distance).
6. Click **Save**.

The device begins polling immediately. States populate within two minutes.

![Public Tempest Station Configuration](https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/configPublic.png)

> **Tip:** You can create as many Public Tempest Station devices as you like — one per station. There is no limit. Each polls independently and maintains its own state set.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Unit Preferences

Each Public Tempest Station device has its own independent unit settings:

| Field | Options |
|---|---|
| **Temperature** | °C (Celsius) or °F (Fahrenheit) |
| **Pressure** | hPa, mmHg, or inHg |
| **Wind Speed** | m/s, km/h, mph, or knots |
| **Rainfall** | mm or inches |
| **Distance** | km or miles (controls `distance_description` format) |

Units are applied at fetch time — the API returns values already in the requested units, so no conversion is performed locally.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Distance and Direction States

Every Public Tempest Station device calculates where the station sits relative to your Indigo server. This requires that Indigo's latitude and longitude are set — open **Indigo → Preferences → Location** to check.

![Public Tempest Station States](https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/publicStates.png)

### How direction is determined

The bearing is measured **from your Indigo server toward the station**. A bearing of `0°` means the station is due North of you; `90°` is East; `180°` South; `270°` West. This gives you an intuitive mental picture: a station whose `bearing_cardinal` is `NNE` lies to the north-north-east of your location.

### Direction and distance states

| State | Example | Description |
|---|---|---|
| `distance_km` | `14.32` | Great-circle distance to the station in kilometres |
| `distance_mi` | `8.90` | Same distance in miles |
| `bearing` | `22.5` | Bearing from Indigo to the station in degrees (0 = North, clockwise) |
| `bearing_cardinal` | `NNE` | 16-point compass rose abbreviation — N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW |
| `distance_description` | `14.3 km NNE` | Human-readable summary — auto-scales to metres below 1 km, or feet below 0.1 miles |

The `distance_description` state is designed for direct display in Control Pages and notifications:

- In kilometres: `"600 m NW"`, `"1.8 km S"`, `"47.2 km ENE"`
- In miles: `"850 ft W"`, `"1.1 mi SSW"`, `"29.3 mi NE"`

> **Example use:** a Control Page label showing `"Coastal station — [distance_description]"` automatically renders as `"Coastal station — 8.4 km WSW"` without any scripting.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Building a Weather Network

Because you can add unlimited Public Tempest Station devices, you can surround your Indigo location with reference stations:

- Compare temperatures across microclimates (coastal vs. inland, valley vs. ridge)
- Identify approaching rain or wind by monitoring upwind stations
- Correlate UV and solar readings across sites
- Watch lightning counts at multiple distances

Each device's `bearing_cardinal` and `distance_description` states tell Indigo automations and Control Pages exactly where each reference station is, without hard-coding labels.

**Example layout:** three stations added, each with a descriptive device name in Indigo:

| Indigo device name | `bearing_cardinal` | `distance_description` |
|---|---|---|
| WF — Harbourside | S | 6.1 km S |
| WF — Ridgeline | NNW | 12.4 km NNW |
| WF — Airport | ENE | 4.8 km ENE |

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Device States

### Station Identity

| State | Description |
|---|---|
| `station_name` | The station's display name as set by its owner |
| `latitude` | Station latitude (decimal degrees) |
| `longitude` | Station longitude (decimal degrees) |
| `elevation` | Station elevation above sea level (metres) |

### Distance and Direction

| State | Description |
|---|---|
| `distance_km` | Distance from Indigo server to station (km) |
| `distance_mi` | Distance from Indigo server to station (miles) |
| `bearing` | Bearing from Indigo server to station (degrees, 0 = North) |
| `bearing_cardinal` | Cardinal abbreviation: N, NNE, NE, ENE … NNW |
| `distance_description` | Human-readable: e.g. `14.3 km NNE` or `8.9 mi NNE` |

### Temperature

| State | Description |
|---|---|
| `air_temperature` | Ambient temperature |
| `dew_point_temperature` | Dew point |
| `wet_bulb_temperature` | Wet bulb temperature |
| `feels_like_temperature` | Apparent / feels-like temperature |
| `heat_index` | Heat index |
| `wind_chill_temperature` | Wind chill |
| `delta_t` | Delta-T (dry bulb minus wet bulb, always °C) |
| `air_density` | Air density (kg/m³) |

### Atmospheric

| State | Description |
|---|---|
| `relative_humidity` | Relative humidity (%) |
| `station_pressure` | Raw station pressure |
| `sea_level_pressure` | Sea-level corrected pressure |
| `pressure_trend` | Pressure tendency: `rising`, `falling`, or `steady` |

### Light and UV

| State | Description |
|---|---|
| `solar_radiation` | Solar irradiance (W/m²) |
| `illuminance` | Illuminance (lux) |
| `uv` | UV index |

### Wind

| State | Description |
|---|---|
| `wind_average` | 1-minute average wind speed |
| `wind_speed` | Alias for `wind_average` |
| `wind_gust` | 1-minute wind gust |
| `wind_lull` | 1-minute wind lull |
| `wind_direction` | Wind direction (degrees) |
| `wind_direction_average` | Alias for `wind_direction` |
| `wind_direction_cardinal` | Cardinal abbreviation (N, NNE, …) |
| `wind_direction_average_cardinal` | Alias for `wind_direction_cardinal` |

### Rain

| State | Description |
|---|---|
| `rain_today` | Rain-check corrected daily total (since local midnight) |
| `rain_yesterday` | Rain-check corrected yesterday total |
| `rain_last_1hr` | Rolling 60-minute rainfall total |
| `rain_duration_today` | Minutes of measurable rain today |
| `rain_duration_yesterday` | Minutes of measurable rain yesterday |

### Lightning

| State | Description |
|---|---|
| `lightning_strike_count` | Total strikes recorded today |
| `lightning_count_last_1hr` | Strikes in the last 60 minutes |
| `lightning_count_last_3hr` | Strikes in the last 3 hours |
| `last_strike_distance` | Distance of the most recent strike (km) |

### Unit Indicators

| State | Description |
|---|---|
| `unit_temperature` | Active temperature unit (e.g. `°C`) |
| `unit_pressure` | Active pressure unit (e.g. `hPa`) |
| `unit_wind` | Active wind speed unit (e.g. `km/h`) |
| `unit_rain` | Active rain unit (e.g. `mm`) |

### Status

| State | Description |
|---|---|
| `deviceStatus` | `Active` when data is flowing; `Waiting for data` on first start; `Suspended` after 3 consecutive poll failures |
| `last_updated` | Timestamp of the observation returned by the API |

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Failure Handling

The plugin tracks consecutive poll failures per station:

- **1–2 failures:** warning logged; polling continues.
- **3 consecutive failures:** polling is suspended and `deviceStatus` is set to `Suspended`. The warning includes the error message.
- **To reset:** edit the device and click Save. The failure counter resets and polling resumes.

Failures are typically caused by a private station (not publicly shared), a mistyped station ID, or a temporary WeatherFlow server error.
