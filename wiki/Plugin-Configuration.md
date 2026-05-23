# Plugin Configuration

Open **Plugins → WeatherFlow Tempest Weather Station → Configure**.

![Plugin Configuration](https://raw.githubusercontent.com/Ghawken/WeatherFlowTempest/main/Images/pluginConfig.png)

---

## Device Generation

Click **Generate Devices** to auto-create one Indigo device for every Tempest and Hub currently broadcasting on the network. Devices are placed in the main Indigo folder and can be moved afterward.

Re-press whenever new Tempest or Hub devices are added to your setup.

---

## UDP Listener Settings

| Setting | Default | Description |
|---|---|---|
| **UDP Port** | `50222` | Port the WeatherFlow hub broadcasts on. Change only if your hub is configured to use a different port. |
| **Listen Address** | `0.0.0.0` | Network interface to listen on. `0.0.0.0` means all interfaces. Set to a specific IP to listen on one interface only. |

Saving the preferences automatically restarts the UDP listener — no plugin reload needed.

---

## WeatherFlow Web API (Optional)

| Setting | Description |
|---|---|
| **Enable Web API** | Tick to activate web-based data polling |
| **API Token** | Your Personal Use Token from [tempestwx.com → Settings → Data Authorizations](https://tempestwx.com/settings/tokens) |

The Web API is optional. When disabled, the plugin operates entirely on local UDP data — no internet connection or account is required.

When enabled, the plugin polls the WeatherFlow REST API to add:

- **Authoritative rain totals** — rain-check corrected daily and yesterday rain
- **Rain last 1 hour** — rolling 60-minute rainfall total
- **Rain duration** — minutes of measurable rain today and yesterday
- **Conditions & icon** — current weather description and icon name
- **Hourly lightning counts** — strikes in the last 1 and 3 hours

See [[Web-API]] for full details including web-only mode for remote hubs.

### Getting a token

1. Log in to [tempestwx.com](https://tempestwx.com).
2. Go to **Settings → Data Authorizations**.
3. Click **Generate Token** and copy the string.

The token is free and tied to your WeatherFlow account. The API only serves stations registered to your account.

---

## Debugging Options

| Setting | Default | Description |
|---|---|---|
| **Indigo Log Level** | Informational | Verbosity of messages in the Indigo Event Log |
| **File Log Level** | Debugging | Verbosity of messages written to the plugin log file |

Available levels (lowest to highest verbosity):

| Level | When to use |
|---|---|
| Detailed Debugging Messages | Deep diagnostics — logs every state change and raw packet |
| Debugging Messages | General troubleshooting |
| Informational Messages | Normal operation — startup, discovery, preferences saved |
| Warning Messages | Only problems and recoveries |
| Error Messages | Only errors |
| Critical Errors Only | Minimal logging |

> **Tip:** Enable *Detailed Debugging Messages* on the File Log Level to capture a full state-change log without flooding the Indigo Event Log. The plugin log file is at `~/Library/Application Support/Perceptive Automation/Indigo 2025.x/Logs/`.

Turn debug logging off again once the issue is resolved — verbose logging has a small performance cost and the log file grows quickly.

---

## Plugin Menu

**Plugins → WeatherFlow Tempest Weather Station** also exposes:

- **List Discovered WeatherFlow Devices** — logs all currently-discovered serial numbers, models, and firmware versions to the Event Log.
- **Restart UDP Listener** — stops and restarts the UDP socket without reloading the plugin. Use this after network changes or if the device dropdown remains empty.
