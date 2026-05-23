<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/banner.png" width="100%">

# Tempest Device Configuration

Open a Tempest Weather Station device to edit its settings.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

![Device Configuration](https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/deviceConfig.png)

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Device Selection

| Field | Description |
|---|---|
| **Tempest Device** | Dropdown of Tempest stations (ST-xxxxxxxx) discovered on the local network via UDP. The list populates automatically once the hub starts broadcasting. Use the **Reload** button if the list is empty. |

> If the hub is on a different network and no devices appear, use **Web-only mode** instead — see below.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Web-only Mode

| Field | Description |
|---|---|
| **Web-only (hub on different network)** | Tick to bypass UDP discovery and source all data from the WeatherFlow Web API |
| **Station ID** | *(visible when web-only is ticked)* Numeric station ID from the WeatherFlow app |

Use this when:
- The hub is on a different network, subnet, or VLAN from the Indigo Mac
- UDP broadcast cannot reach the Indigo Mac
- You want a fully cloud-sourced device with no dependency on local networking

The Web API must be enabled with a valid token in **Plugin Preferences** for web-only mode to work. The device polls every 60 seconds and all sensor states (temperature, pressure, wind, rain, UV, lightning, conditions) are populated from the web. `deviceStatus` shows **Active (web)** when data is flowing.

**Finding your Station ID:** Open the WeatherFlow app, tap your station name, then tap **Settings**. The station ID is also visible in the URL on tempestwx.com — e.g. `tempestwx.com/station/`**183063**.

See [[Web-API]] for full details.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Altitude

| Field | Default | Description |
|---|---|---|
| **Altitude (m)** | `0` | Station elevation in metres above sea level |

Set to a non-zero value to enable three derived states:

| State | Description |
|---|---|
| `sea_level_pressure` | Station pressure corrected to sea level |
| `cloud_base` | Estimated cloud base height above station |
| `freezing_level` | Estimated freezing level height above station |

Set to `0` to omit these states entirely (they will not appear in the device state list).

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Measurement Units

All unit selections are independent — mix and match as needed.

| Setting | Options | Default |
|---|---|---|
| **Temperature** | Celsius (°C), Fahrenheit (°F) | Celsius |
| **Pressure** | hPa (mbar), mmHg, inHg | hPa |
| **Wind Speed** | m/s, km/h, knots, mph | m/s |
| **Rainfall** | Millimetres (mm), Inches (in) | mm |
| **Altitude** | Metres (m), Feet (ft) | m |

Changes take effect on the **next sensor observation** (within ~1 minute for a normal Tempest). The active unit for each category is also stored as a device state:

| State | Example value |
|---|---|
| `unit_temperature` | `°C` |
| `unit_pressure` | `hPa` |
| `unit_wind` | `km/h` |
| `unit_rain` | `mm` |

These states make it easy to display the correct unit label on Indigo control pages without hardcoding it.

<img src="https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/weather_divider_top_animated.gif" width="100%">

## Tips

- **Changing units** does not require a device recreate — edit the device, change the unit, and save. The next observation updates all affected states.
- **Adding altitude later** is safe — set the value, save, and the derived states appear on the next observation.
- **Multiple Tempests** each get their own Indigo device with independent unit settings. Each can be configured for different unit preferences if needed.
