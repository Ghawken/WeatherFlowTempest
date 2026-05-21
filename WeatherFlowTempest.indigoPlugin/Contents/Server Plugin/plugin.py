"""WeatherFlow Tempest Weather Station plugin for Indigo home automation.

Listens for WeatherFlow UDP broadcasts (port 50222) using the pyweatherflowudp
library and maps all sensor observations to Indigo device states.

Architecture: asyncio event loop running in a daemon thread alongside Indigo's
own threading model, following the pattern used by appleTV-indigoPlugin and
HomeKitLink-Siri. Indigo's updateStatesOnServer() is thread-safe and is called
directly from async callbacks.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import indigo  # type: ignore

from pyweatherflowudp.client import EVENT_DEVICE_DISCOVERED, WeatherFlowListener
from pyweatherflowudp.const import (
    DEFAULT_PORT,
    EVENT_RAIN_START,
    EVENT_RAPID_WIND,
    EVENT_STRIKE,
    units,
)
from pyweatherflowudp.device import (
    EVENT_LOAD_COMPLETE,
    EVENT_OBSERVATION,
    EVENT_STATUS_UPDATE,
    AirSensorType,
    HubDevice,
    SkySensorType,
    TempestDevice,
    WeatherFlowDevice,
    WeatherFlowSensorDevice,
)
from pyweatherflowudp.errors import ListenerError


class Plugin(indigo.PluginBase):
    """WeatherFlow Tempest Weather Station plugin."""

    def __init__(
        self,
        pluginId: str,
        pluginDisplayName: str,
        pluginVersion: str,
        pluginPrefs: dict,
    ) -> None:
        super().__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter(
            "%(asctime)s.%(msecs)03d\t%(levelname)s\t%(name)s.%(funcName)s:\t%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.plugin_file_handler.setFormatter(pfmt)

        # Logger must be DEBUG so messages reach both handlers;
        # each handler then applies its own level filter independently.
        self.logger.setLevel(logging.DEBUG)

        try:
            self.logLevel = int(pluginPrefs.get("showDebugLevel", logging.INFO))
        except (ValueError, TypeError):
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)

        try:
            fileLevel = int(pluginPrefs.get("showDebugFileLevel", logging.DEBUG))
        except (ValueError, TypeError):
            fileLevel = logging.DEBUG
        self.plugin_file_handler.setLevel(fileLevel)

        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._async_thread: threading.Thread | None = None
        self._listener: WeatherFlowListener | None = None

        # serial_number -> WeatherFlowDevice
        self._discovered: dict[str, WeatherFlowDevice] = {}
        # serial_number -> indigo device id
        self._serial_to_dev_id: dict[str, int] = {}
        # serial_number -> list of unsubscribe callables
        self._unsubs: dict[str, list[Any]] = {}

    # -------------------------------------------------------------------------
    # Plugin lifecycle
    # -------------------------------------------------------------------------

    def startup(self) -> None:
        self.logger.info("WeatherFlow Tempest: starting")

        self._event_loop = asyncio.new_event_loop()
        self._async_thread = threading.Thread(
            target=self._event_loop.run_forever,
            daemon=True,
            name="WeatherFlowEventLoop",
        )
        self._async_thread.start()

        for dev in indigo.devices.iter("self"):
            sn = dev.pluginProps.get("serialNumber", "").strip()
            if sn:
                self._serial_to_dev_id[sn] = dev.id

        asyncio.run_coroutine_threadsafe(self._start_listener(), self._event_loop)

    def shutdown(self) -> None:
        self.logger.info("WeatherFlow Tempest: shutting down")
        if self._listener and self._event_loop and self._event_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._listener.stop_listening(), self._event_loop
            )
        if self._event_loop and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)

    def runConcurrentThread(self) -> None:
        try:
            while True:
                self.sleep(60)
                if (
                    self._listener
                    and not self._listener.is_listening
                    and self._event_loop
                ):
                    self.logger.warning("WeatherFlow listener stopped, restarting")
                    asyncio.run_coroutine_threadsafe(
                        self._start_listener(), self._event_loop
                    )
        except self.StopThread:
            pass

    def stopConcurrentThread(self) -> None:
        self.stopThread = True

    # -------------------------------------------------------------------------
    # Async listener management
    # -------------------------------------------------------------------------

    async def _start_listener(self) -> None:
        port = int(self.pluginPrefs.get("udpPort", DEFAULT_PORT))
        host = self.pluginPrefs.get("udpHost", "0.0.0.0")
        try:
            self._listener = WeatherFlowListener(host=host, port=port)
            self._listener.on(EVENT_DEVICE_DISCOVERED, self._on_device_discovered)
            await self._listener.start_listening()
            self.logger.info("WeatherFlow UDP listener started on %s:%d", host, port)
        except ListenerError as ex:
            self.logger.error("WeatherFlow listener error: %s", ex)
        except Exception as ex:
            self.logger.error("Failed to start WeatherFlow listener: %s", ex)

    async def _restart_listener(self) -> None:
        if self._listener:
            try:
                await self._listener.stop_listening()
            except Exception:
                pass
        # Old listener's device objects are dead. Flush stale subscriptions and
        # the discovered cache so _on_device_discovered re-subscribes to the
        # fresh device objects the new listener creates.
        for sn in list(self._unsubs.keys()):
            self._unsubscribe(sn)
        self._discovered.clear()
        await self._start_listener()

    # -------------------------------------------------------------------------
    # Device discovery
    # -------------------------------------------------------------------------

    def _on_device_discovered(self, device: WeatherFlowDevice) -> None:
        sn = device.serial_number
        self._discovered[sn] = device
        self.logger.info("Discovered WeatherFlow device: %s  model=%s", sn, device.model)

        if isinstance(device, WeatherFlowSensorDevice):
            self._subscribe_sensor(device)
        elif isinstance(device, HubDevice):
            self._subscribe_hub(device)

    def _subscribe_sensor(self, device: WeatherFlowSensorDevice) -> None:
        sn = device.serial_number
        if sn in self._unsubs:
            return

        unsubs: list[Any] = [
            device.on(EVENT_OBSERVATION,  lambda _ev, d=device: self._on_observation(d)),
            device.on(EVENT_STATUS_UPDATE, lambda _ev, d=device: self._on_status_update(d)),
            device.on(EVENT_RAPID_WIND,    lambda _ev, d=device: self._on_rapid_wind(d)),
            device.on(EVENT_LOAD_COMPLETE, lambda _ev, d=device: self._on_load_complete(d)),
        ]
        if isinstance(device, AirSensorType):
            unsubs.append(
                device.on(EVENT_STRIKE,     lambda ev,  d=device: self._on_strike(d, ev))
            )
        if isinstance(device, SkySensorType):
            unsubs.append(
                device.on(EVENT_RAIN_START, lambda ev,  d=device: self._on_rain_start(d, ev))
            )
        self._unsubs[sn] = unsubs

    def _subscribe_hub(self, device: HubDevice) -> None:
        sn = device.serial_number
        if sn in self._unsubs:
            return
        self._unsubs[sn] = [
            device.on(EVENT_STATUS_UPDATE, lambda _ev, d=device: self._on_hub_status(d)),
            device.on(EVENT_LOAD_COMPLETE, lambda _ev, d=device: self._on_hub_status(d)),
        ]

    def _unsubscribe(self, serial_number: str) -> None:
        for fn in self._unsubs.pop(serial_number, []):
            try:
                fn()
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Trigger helper
    # -------------------------------------------------------------------------

    def _check_triggers(
        self, event_type_id: str, indigo_dev_id: int, **kwargs: Any
    ) -> None:
        for trigger in indigo.triggers.iter("self"):
            if not trigger.enabled:
                continue
            if trigger.pluginTypeId != event_type_id:
                continue
            try:
                if int(trigger.pluginProps.get("deviceId", 0)) != indigo_dev_id:
                    continue
            except (ValueError, TypeError):
                continue

            if event_type_id == "rapidWindThreshold":
                try:
                    threshold = float(trigger.pluginProps.get("threshold", 0.0))
                    if kwargs.get("speed_ms", 0.0) < threshold:
                        continue
                except (ValueError, TypeError):
                    continue

            indigo.trigger.execute(trigger)

    # -------------------------------------------------------------------------
    # Event handlers (called from async thread — Indigo API is thread-safe)
    # -------------------------------------------------------------------------

    def _on_load_complete(self, device: WeatherFlowSensorDevice) -> None:
        try:
            self.logger.info(
                "%s: initial data load complete (firmware=%s)",
                device.serial_number,
                device.firmware_revision,
            )
            self._on_observation(device)
            self._on_status_update(device)
        except Exception:
            self.logger.exception("%s: error in load-complete handler", device.serial_number)

    def _on_observation(self, device: WeatherFlowSensorDevice) -> None:
        try:
            dev = self._get_indigo_dev(device.serial_number)
            if dev is None:
                return
            altitude_qty = self._get_altitude(dev)
            unit_prefs = _get_unit_prefs(dev)
            states = _build_observation_states(device, altitude_qty, unit_prefs)
            if states:
                dev.updateStatesOnServer(states)
        except Exception:
            self.logger.exception("%s: error in observation handler", device.serial_number)

    def _on_status_update(self, device: WeatherFlowSensorDevice) -> None:
        try:
            dev = self._get_indigo_dev(device.serial_number)
            if dev is None:
                return
            states = _build_status_states(device)
            if states:
                dev.updateStatesOnServer(states)
        except Exception:
            self.logger.exception("%s: error in status-update handler", device.serial_number)

    def _on_rapid_wind(self, device: WeatherFlowSensorDevice) -> None:
        try:
            dev = self._get_indigo_dev(device.serial_number)
            if dev is None:
                return
            unit_prefs = _get_unit_prefs(dev)
            states = _build_wind_states(device, unit_prefs)
            if states:
                dev.updateStatesOnServer(states)
            # Threshold comparison always uses raw m/s magnitude
            speed_ms = (
                float(device.wind_speed.magnitude) if device.wind_speed is not None else 0.0
            )
            self._check_triggers("rapidWindThreshold", dev.id, speed_ms=speed_ms)
            self.logger.debug("%s: rapid wind %.2f m/s", device.serial_number, speed_ms)
        except Exception:
            self.logger.exception("%s: error in rapid-wind handler", device.serial_number)

    def _on_strike(self, device: WeatherFlowSensorDevice, event: Any) -> None:
        try:
            dev = self._get_indigo_dev(device.serial_number)
            if dev is None:
                return
            unit_prefs = _get_unit_prefs(dev)
            states: list[dict] = []
            if device.lightning_strike_count is not None:
                states.append(
                    {"key": "lightning_strike_count", "value": device.lightning_strike_count}
                )
            _add_u(states, "lightning_strike_average_distance",
                   device.lightning_strike_average_distance, "distance", unit_prefs)
            if event is not None:
                _add_u(states, "last_strike_distance", event.distance, "distance", unit_prefs)
                states.append({"key": "last_strike_energy", "value": int(event.energy)})
            if states:
                dev.updateStatesOnServer(states)
            self._check_triggers("lightningStrike", dev.id)
            self.logger.debug("%s: lightning strike", device.serial_number)
        except Exception:
            self.logger.exception("%s: error in strike handler", device.serial_number)

    def _on_rain_start(self, device: WeatherFlowSensorDevice, event: Any) -> None:
        try:
            dev = self._get_indigo_dev(device.serial_number)
            if dev is None:
                return
            if event is not None:
                ts = str(event.timestamp) if event.timestamp else ""
                dev.updateStateOnServer("last_rain_start", ts)
            self._check_triggers("rainStart", dev.id)
            self.logger.debug("%s: rain start", device.serial_number)
        except Exception:
            self.logger.exception("%s: error in rain-start handler", device.serial_number)

    def _on_hub_status(self, device: HubDevice) -> None:
        try:
            dev = self._get_indigo_dev(device.serial_number)
            if dev is None:
                return
            states: list[dict] = []
            if device.firmware_revision:
                states.append({"key": "firmware_revision", "value": str(device.firmware_revision)})
            _add_int(states, "rssi", device.rssi)
            if device.up_since:
                states.append({"key": "up_since", "value": str(device.up_since)})
            if device.uptime is not None:
                _add_int(states, "uptime", device.uptime)
            if device.reset_flags is not None:
                flag_str = (
                    ", ".join(str(f) for f in device.reset_flags)
                    if device.reset_flags else "none"
                )
                states.append({"key": "reset_flags", "value": flag_str})
            if states:
                states.append({"key": "deviceStatus", "value": "Active"})
                dev.updateStatesOnServer(states)
        except Exception:
            self.logger.exception("%s: error in hub-status handler", device.serial_number)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_indigo_dev(self, serial_number: str):
        dev_id = self._serial_to_dev_id.get(serial_number)
        if dev_id is None:
            return None
        return indigo.devices.get(dev_id)

    @staticmethod
    def _get_altitude(dev) -> Any:
        try:
            alt = float(dev.pluginProps.get("altitude", 0))
            if alt != 0.0:
                return units.Quantity(alt, "m")
        except (ValueError, TypeError):
            pass
        return None

    # -------------------------------------------------------------------------
    # Indigo device lifecycle
    # -------------------------------------------------------------------------

    def deviceStartComm(self, device) -> None:
        # Sync state definitions from Devices.xml — picks up new states added
        # in plugin updates without requiring the user to delete/recreate devices.
        device.stateListOrDisplayStateIdChanged()

        sn = device.pluginProps.get("serialNumber", "").strip()
        if not sn:
            self.logger.warning("%s: no serial number configured", device.name)
            return

        self._serial_to_dev_id[sn] = device.id
        device.updateStateOnServer("deviceStatus", "Waiting for data")
        self.logger.info("%s (%s): comm started", device.name, sn)

        wf_dev = self._discovered.get(sn)
        if wf_dev is not None:
            # Subscribe if not already done (discovery may have beaten deviceStartComm)
            if sn not in self._unsubs:
                if isinstance(wf_dev, WeatherFlowSensorDevice):
                    self._subscribe_sensor(wf_dev)
                elif isinstance(wf_dev, HubDevice):
                    self._subscribe_hub(wf_dev)

            # Always populate from whatever data the device already has
            if isinstance(wf_dev, WeatherFlowSensorDevice):
                altitude_qty = self._get_altitude(device)
                unit_prefs = _get_unit_prefs(device)
                states = _build_observation_states(wf_dev, altitude_qty, unit_prefs)
                states.extend(_build_status_states(wf_dev))
                if states:
                    device.updateStatesOnServer(states)
            elif isinstance(wf_dev, HubDevice):
                self._on_hub_status(wf_dev)

    def deviceStopComm(self, device) -> None:
        sn = device.pluginProps.get("serialNumber", "").strip()
        if sn:
            self._unsubscribe(sn)
            self._serial_to_dev_id.pop(sn, None)
        self.logger.info("%s: comm stopped", device.name)

    # -------------------------------------------------------------------------
    # Plugin config UI
    # -------------------------------------------------------------------------

    def validatePluginConfigUi(self, valuesDict, typeId, devId):
        errors = indigo.Dict()
        try:
            port = int(valuesDict.get("udpPort", str(DEFAULT_PORT)))
            if not 1024 <= port <= 65535:
                raise ValueError
        except (ValueError, TypeError):
            errors["udpPort"] = "Port must be an integer between 1024 and 65535"
        if errors:
            return False, valuesDict, errors
        return True, valuesDict, errors

    def closedPluginConfigUi(self, valuesDict, userCancelled) -> None:
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict.get("showDebugLevel", logging.INFO))
                self.indigo_log_handler.setLevel(self.logLevel)
            except (ValueError, TypeError):
                pass
            try:
                fileLevel = int(valuesDict.get("showDebugFileLevel", logging.DEBUG))
                self.plugin_file_handler.setLevel(fileLevel)
            except (ValueError, TypeError):
                pass
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    self._restart_listener(), self._event_loop
                )

    # -------------------------------------------------------------------------
    # Device config UI
    # -------------------------------------------------------------------------

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        errors = indigo.Dict()
        sn = valuesDict.get("serialNumber", "").strip()
        if not sn:
            errors["serialNumber"] = (
                "No device selected. Wait for discovery or check hub is on the same network."
            )
            return False, valuesDict, errors
        return True, valuesDict, errors

    def getDiscoveredDeviceList(self, filter="", valuesDict=None, typeId="", targetId=0):
        items = []
        for sn, dev in self._discovered.items():
            if typeId == "tempestStation" and not sn.startswith("ST"):
                continue
            if typeId == "hubStation" and not sn.startswith("HB"):
                continue
            items.append((sn, f"{sn}  ({dev.model})"))
        if not items:
            items.append(("", "── No devices discovered yet ──"))
        return items

    # -------------------------------------------------------------------------
    # Plugin config — device generation
    # -------------------------------------------------------------------------

    def generateDevices(self, valuesDict=None, typeId=""):
        if not self._discovered:
            self.logger.warning(
                "No WeatherFlow devices discovered yet. "
                "Ensure the hub is on the same subnet and UDP port %d is reachable.",
                int(self.pluginPrefs.get("udpPort", DEFAULT_PORT)),
            )
            return valuesDict

        existing_serials: set[str] = set()
        for dev in indigo.devices.iter("self"):
            sn = dev.pluginProps.get("serialNumber", "").strip()
            if sn:
                existing_serials.add(sn)

        created = 0
        for sn, wf_dev in self._discovered.items():
            if sn in existing_serials:
                self.logger.info("  %s: Indigo device already exists, skipping", sn)
                continue
            if sn.startswith("ST"):
                dev_type_id = "tempestStation"
            elif sn.startswith("HB"):
                dev_type_id = "hubStation"
            else:
                self.logger.debug("  %s: unknown serial prefix, skipping", sn)
                continue

            dev_name = f"WeatherFlow {wf_dev.model} {sn}"
            props = {
                "serialNumber": sn,
                "altitude": "0",
                "tempUnit":     "celsius",
                "pressureUnit": "hpa",
                "windUnit":     "ms",
                "rainUnit":     "mm",
                "altUnit":      "m",
            }
            try:
                new_dev = indigo.device.create(
                    protocol=indigo.kProtocol.Plugin,
                    name=dev_name,
                    pluginId=self.pluginId,
                    deviceTypeId=dev_type_id,
                    props=props,
                )
                self.logger.info("Created device: %s  (id=%d)", dev_name, new_dev.id)
                created += 1
            except Exception as ex:
                self.logger.error("Failed to create device %s: %s", dev_name, ex)

        if created == 0:
            self.logger.info("All discovered devices already have Indigo devices.")
        else:
            self.logger.info(
                "Generated %d new device(s) from %d discovered.", created, len(self._discovered)
            )
        return valuesDict

    # -------------------------------------------------------------------------
    # Menu items
    # -------------------------------------------------------------------------

    def menuListDiscoveredDevices(self):
        if not self._discovered:
            self.logger.info(
                "No WeatherFlow devices discovered yet. "
                "Ensure hub is on the same subnet and UDP port %d is not blocked.",
                int(self.pluginPrefs.get("udpPort", DEFAULT_PORT)),
            )
            return
        self.logger.info("Discovered WeatherFlow devices (%d):", len(self._discovered))
        for sn, dev in self._discovered.items():
            self.logger.info(
                "  %s  model=%-8s  firmware=%s", sn, dev.model, dev.firmware_revision
            )

    def menuRestartListener(self):
        self.logger.info("WeatherFlow: manually restarting UDP listener")
        if self._event_loop:
            asyncio.run_coroutine_threadsafe(self._restart_listener(), self._event_loop)


# =============================================================================
# Unit conversion tables
#
# _UNIT_SPECS:
#   (category, unit_id) → (display_symbol, decimal_places, pint_target, manual_factor)
#   pint_target:   str  → call qty.to(pint_target) for conversion
#   manual_factor: float → multiply raw magnitude (used when Pint target is unreliable)
#   Both None means use the raw magnitude unchanged.
#
# _FIXED_SPECS:
#   category → (display_symbol, decimal_places)
#   Categories with no per-device unit selection.
# =============================================================================

_UNIT_SPECS: dict[tuple, tuple] = {
    # Temperature (absolute — Pint handles the offset correctly)
    ("temp",     "celsius"):    ("°C",   1, None,   None),
    ("temp",     "fahrenheit"): ("°F",   1, "degF", None),

    # Pressure (pyweatherflowudp stores as mbar; 1 mbar == 1 hPa exactly)
    ("pressure", "hpa"):   ("hPa",  1, None,   None),
    ("pressure", "mmhg"):  ("mmHg", 1, None,   0.750062),
    ("pressure", "inhg"):  ("inHg", 4, "inHg", None),

    # Wind speed
    ("wind",  "ms"):    ("m/s",  1, None,  None),
    ("wind",  "kmh"):   ("km/h", 1, None,  3.6),
    ("wind",  "knots"): ("kn",   1, None,  1.94384),
    ("wind",  "mph"):   ("mph",  1, "mph", None),

    # Rainfall
    ("rain",      "mm"):   ("mm",   2, None,   None),
    ("rain",      "inch"): ("in",   3, "inch", None),

    # Rain rate (inch/h uses manual factor — Pint's "inch/hour" spelling is uncertain)
    ("rain_rate", "mm"):   ("mm/h", 2, None,   None),
    ("rain_rate", "inch"): ("in/h", 3, None,   0.0393701),

    # Altitude (cloud base, freezing level)
    ("alt",  "m"):  ("m",  0, None,   None),
    ("alt",  "ft"): ("ft", 0, "foot", None),

    # Distance (lightning) — not user-selectable, always km
    ("distance", "km"): ("km", 1, None,   None),
    ("distance", "mi"): ("mi", 1, "mile", None),
}

_FIXED_SPECS: dict[str, tuple] = {
    "percent":    ("%",     1),
    "density":    ("kg/m³", 3),
    "lux":        ("lx",    0),
    "irradiance": ("W/m²",  0),
    "volts":      ("V",     2),
    "dbm":        ("dBm",   0),
    "degrees":    ("°",     1),
    "uv":         ("UV",    1),
    "delta_t":    ("Δ°C",   1),   # temperature differential — stays in °C
    "count":      ("",      0),
}

_DEFAULT_UNIT_IDS: dict[str, str] = {
    "temp":      "celsius",
    "pressure":  "hpa",
    "wind":      "ms",
    "rain":      "mm",
    "rain_rate": "mm",
    "alt":       "m",
    "distance":  "km",
}

_UNIT_DISPLAY: dict[str, str] = {
    "celsius":    "°C",
    "fahrenheit": "°F",
    "hpa":        "hPa",
    "mmhg":       "mmHg",
    "inhg":       "inHg",
    "ms":         "m/s",
    "kmh":        "km/h",
    "knots":      "kn",
    "mph":        "mph",
    "mm":         "mm",
    "inch":       "in",
    "m":          "m",
    "ft":         "ft",
}


def _get_unit_prefs(dev) -> dict:
    """Return a unit-preference dict from an Indigo device's pluginProps.

    Supports both the new per-category props and the legacy binary unitSystem prop
    so existing devices continue to work after a plugin update.
    """
    props = dev.pluginProps
    legacy_imperial = props.get("unitSystem", "metric") == "imperial"
    rain_unit = props.get("rainUnit", "inch" if legacy_imperial else "mm")
    return {
        "temp":      props.get("tempUnit",     "fahrenheit" if legacy_imperial else "celsius"),
        "pressure":  props.get("pressureUnit", "inhg"       if legacy_imperial else "hpa"),
        "wind":      props.get("windUnit",     "mph"        if legacy_imperial else "ms"),
        "rain":      rain_unit,
        "rain_rate": rain_unit,
        "alt":       props.get("altUnit",      "ft"         if legacy_imperial else "m"),
        "distance":  "km",
    }


def _build_unit_states(unit_prefs: dict) -> list:
    """Return four String states that show the active unit for each measurement type."""
    return [
        {"key": "unit_temperature",
         "value": _UNIT_DISPLAY.get(unit_prefs.get("temp",     "celsius"), "°C")},
        {"key": "unit_pressure",
         "value": _UNIT_DISPLAY.get(unit_prefs.get("pressure", "hpa"),     "hPa")},
        {"key": "unit_wind",
         "value": _UNIT_DISPLAY.get(unit_prefs.get("wind",     "ms"),      "m/s")},
        {"key": "unit_rain",
         "value": _UNIT_DISPLAY.get(unit_prefs.get("rain",     "mm"),      "mm")},
    ]


def _add_u(
    states: list[dict], key: str, qty: Any, category: str, unit_prefs: dict
) -> None:
    """Convert qty to the user-selected unit and append a state dict entry."""
    if qty is None:
        return
    try:
        raw = float(qty.magnitude if hasattr(qty, "magnitude") else qty)
    except (TypeError, ValueError, AttributeError):
        return

    if category in _FIXED_SPECS:
        sym, dp = _FIXED_SPECS[category]
        mag = raw
    else:
        unit_id = unit_prefs.get(category) or _DEFAULT_UNIT_IDS.get(category, "")
        spec = _UNIT_SPECS.get((category, unit_id))
        if spec is None:
            return
        sym, dp, pint_tgt, factor = spec
        try:
            if pint_tgt is not None and hasattr(qty, "to"):
                mag = float(qty.to(pint_tgt).magnitude)
            elif factor is not None:
                mag = raw * factor
            else:
                mag = raw
        except Exception:
            return

    try:
        val = round(mag, dp)
        entry: dict = {"key": key, "value": val, "decimalPlaces": dp}
        if sym:
            entry["uiValue"] = f"{val} {sym}"
        states.append(entry)
    except Exception:
        pass


# =============================================================================
# State builder functions (module-level, no Plugin instance needed)
# =============================================================================

def _build_observation_states(
    device: WeatherFlowSensorDevice,
    altitude_qty: Any = None,
    unit_prefs: dict | None = None,
) -> list[dict]:
    if unit_prefs is None:
        unit_prefs = {}
    states: list[dict] = []

    # --- Temperature ---
    _add_u(states, "air_temperature",        device.air_temperature,       "temp",    unit_prefs)
    _add_u(states, "dew_point_temperature",  device.dew_point_temperature, "temp",    unit_prefs)
    _add_u(states, "wet_bulb_temperature",   device.wet_bulb_temperature,  "temp",    unit_prefs)
    _add_u(states, "heat_index",             device.heat_index,            "temp",    unit_prefs)
    _add_u(states, "delta_t",               device.delta_t,               "delta_t", unit_prefs)

    if isinstance(device, TempestDevice):
        _add_u(states, "feels_like_temperature", device.feels_like_temperature, "temp", unit_prefs)
        _add_u(states, "wind_chill_temperature", device.wind_chill_temperature, "temp", unit_prefs)

    # --- Atmospheric ---
    _add_u(states, "relative_humidity", device.relative_humidity, "percent",  unit_prefs)
    _add_u(states, "station_pressure",  device.station_pressure,  "pressure", unit_prefs)
    _add_u(states, "vapor_pressure",    device.vapor_pressure,    "pressure", unit_prefs)
    _add_u(states, "air_density",       device.air_density,       "density",  unit_prefs)

    if altitude_qty is not None:
        try:
            _add_u(states, "sea_level_pressure",
                   device.calculate_sea_level_pressure(altitude_qty), "pressure", unit_prefs)
        except Exception:
            pass
        try:
            _add_u(states, "cloud_base",
                   device.calculate_cloud_base(altitude_qty), "alt", unit_prefs)
        except Exception:
            pass
        try:
            _add_u(states, "freezing_level",
                   device.calculate_freezing_level(altitude_qty), "alt", unit_prefs)
        except Exception:
            pass

    # --- Light / UV ---
    _add_u(states, "illuminance",     device.illuminance,     "lux",        unit_prefs)
    _add_u(states, "solar_radiation", device.solar_radiation, "irradiance", unit_prefs)
    _add_u(states, "uv",              device.uv,              "uv",         unit_prefs)

    # --- Rain ---
    _add_u(states, "rain_accumulation_previous_minute",
           device.rain_accumulation_previous_minute, "rain", unit_prefs)
    _add_u(states, "rain_rate", device.rain_rate, "rain_rate", unit_prefs)
    if device.precipitation_type is not None:
        states.append({"key": "precipitation_type",
                       "value": device.precipitation_type.name.lower()})

    # --- Lightning ---
    if device.lightning_strike_count is not None:
        states.append({"key": "lightning_strike_count",
                       "value": device.lightning_strike_count})
    _add_u(states, "lightning_strike_average_distance",
           device.lightning_strike_average_distance, "distance", unit_prefs)

    # --- Wind ---
    states.extend(_build_wind_states(device, unit_prefs))

    # --- Battery ---
    _add_u(states, "battery",         device.battery,         "volts",   unit_prefs)
    _add_u(states, "battery_percent", device.battery_percent, "percent", unit_prefs)

    # --- Timestamps / diagnostics ---
    if device.last_report:
        states.append({"key": "last_report", "value": str(device.last_report)})

    if isinstance(device, TempestDevice) and device.power_save_mode is not None:
        states.append({"key": "power_save_mode", "value": device.power_save_mode.name})

    # --- Unit indicators ---
    states.extend(_build_unit_states(unit_prefs))

    states.append({"key": "deviceStatus", "value": "Active"})
    return states


def _build_wind_states(
    device: WeatherFlowSensorDevice, unit_prefs: dict | None = None
) -> list[dict]:
    if unit_prefs is None:
        unit_prefs = {}
    states: list[dict] = []
    _add_u(states, "wind_speed",             device.wind_speed,             "wind",    unit_prefs)
    _add_u(states, "wind_average",           device.wind_average,           "wind",    unit_prefs)
    _add_u(states, "wind_gust",              device.wind_gust,              "wind",    unit_prefs)
    _add_u(states, "wind_lull",              device.wind_lull,              "wind",    unit_prefs)
    _add_u(states, "wind_direction",         device.wind_direction,         "degrees", unit_prefs)
    _add_u(states, "wind_direction_average", device.wind_direction_average, "degrees", unit_prefs)
    cardinal = device.wind_direction_cardinal
    if cardinal:
        states.append({"key": "wind_direction_cardinal", "value": cardinal})
    avg_cardinal = device.wind_direction_average_cardinal
    if avg_cardinal:
        states.append({"key": "wind_direction_average_cardinal", "value": avg_cardinal})
    return states


def _build_status_states(device: WeatherFlowSensorDevice) -> list[dict]:
    states: list[dict] = []
    _add_int(states, "rssi",     device.rssi)
    _add_int(states, "hub_rssi", device.hub_rssi)
    if device.firmware_revision:
        states.append({"key": "firmware_revision", "value": str(device.firmware_revision)})
    if device.hub_sn:
        states.append({"key": "hub_sn", "value": str(device.hub_sn)})
    if device.up_since:
        states.append({"key": "up_since", "value": str(device.up_since)})
    sensor_status = device.sensor_status
    if sensor_status is not None:
        states.append({"key": "sensor_status",
                       "value": ", ".join(sensor_status) if sensor_status else "OK"})
    return states


def _add_int(states: list[dict], key: str, value: Any) -> None:
    if value is None:
        return
    try:
        mag = value.magnitude if hasattr(value, "magnitude") else value
        states.append({"key": key, "value": int(mag)})
    except (TypeError, AttributeError, ValueError):
        pass
