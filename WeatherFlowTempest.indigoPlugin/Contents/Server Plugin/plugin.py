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

        try:
            self.logLevel = int(pluginPrefs.get("showDebugLevel", logging.INFO))
        except (ValueError, TypeError):
            self.logLevel = logging.INFO
        self.logger.setLevel(self.logLevel)
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

        # Build serial->dev_id map from already-configured Indigo devices
        for dev in indigo.devices.iter("self"):
            sn = dev.pluginProps.get("serialNumber", "").strip()
            if sn:
                self._serial_to_dev_id[sn] = dev.id

        asyncio.run_coroutine_threadsafe(self._start_listener(), self._event_loop)

    def shutdown(self) -> None:
        self.logger.info("WeatherFlow Tempest: shutting down")
        if self._listener and self._event_loop:
            fut = asyncio.run_coroutine_threadsafe(
                self._listener.stop_listening(), self._event_loop
            )
            try:
                fut.result(timeout=10)
            except Exception as ex:
                self.logger.debug("Listener stop: %s", ex)
        if self._event_loop and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)

    def runConcurrentThread(self) -> None:
        try:
            while True:
                self.sleep(60)
                if self._listener and not self._listener.is_listening and self._event_loop:
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
            self.logger.info(
                "WeatherFlow UDP listener started on %s:%d", host, port
            )
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
        await self._start_listener()

    # -------------------------------------------------------------------------
    # Device discovery (called from async thread; all Indigo API calls are safe)
    # -------------------------------------------------------------------------

    def _on_device_discovered(self, device: WeatherFlowDevice) -> None:
        sn = device.serial_number
        self._discovered[sn] = device
        self.logger.info(
            "Discovered WeatherFlow device: %s  model=%s", sn, device.model
        )

        if isinstance(device, WeatherFlowSensorDevice):
            self._subscribe_sensor(device)
        elif isinstance(device, HubDevice):
            self._subscribe_hub(device)

    def _subscribe_sensor(self, device: WeatherFlowSensorDevice) -> None:
        sn = device.serial_number
        if sn in self._unsubs:
            return  # already subscribed

        unsubs: list[Any] = [
            device.on(EVENT_OBSERVATION, lambda _ev, d=device: self._on_observation(d)),
            device.on(EVENT_STATUS_UPDATE, lambda _ev, d=device: self._on_status_update(d)),
            device.on(EVENT_RAPID_WIND, lambda _ev, d=device: self._on_rapid_wind(d)),
            device.on(EVENT_LOAD_COMPLETE, lambda _ev, d=device: self._on_load_complete(d)),
        ]
        if isinstance(device, AirSensorType):
            unsubs.append(
                device.on(EVENT_STRIKE, lambda ev, d=device: self._on_strike(d, ev))
            )
        if isinstance(device, SkySensorType):
            unsubs.append(
                device.on(EVENT_RAIN_START, lambda ev, d=device: self._on_rain_start(d, ev))
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
    # Event handlers (called from async thread)
    # -------------------------------------------------------------------------

    def _on_load_complete(self, device: WeatherFlowSensorDevice) -> None:
        self.logger.info(
            "%s: initial data load complete (firmware=%s)",
            device.serial_number,
            device.firmware_revision,
        )
        self._on_observation(device)
        self._on_status_update(device)

    def _on_observation(self, device: WeatherFlowSensorDevice) -> None:
        dev = self._get_indigo_dev(device.serial_number)
        if dev is None:
            return
        altitude_qty = self._get_altitude(dev)
        states = _build_observation_states(device, altitude_qty)
        if states:
            dev.updateStatesOnServer(states)

    def _on_status_update(self, device: WeatherFlowSensorDevice) -> None:
        dev = self._get_indigo_dev(device.serial_number)
        if dev is None:
            return
        states = _build_status_states(device)
        if states:
            dev.updateStatesOnServer(states)

    def _on_rapid_wind(self, device: WeatherFlowSensorDevice) -> None:
        dev = self._get_indigo_dev(device.serial_number)
        if dev is None:
            return
        states = _build_wind_states(device)
        if states:
            dev.updateStatesOnServer(states)

    def _on_strike(self, device: WeatherFlowSensorDevice, event: Any) -> None:
        dev = self._get_indigo_dev(device.serial_number)
        if dev is None:
            return
        states: list[dict] = []
        if device.lightning_strike_count is not None:
            states.append({"key": "lightning_strike_count",
                           "value": device.lightning_strike_count})
        _add_float(states, "lightning_strike_average_distance",
                   device.lightning_strike_average_distance, 2)
        if event is not None:
            states.append({"key": "last_strike_distance",
                           "value": round(float(event.distance.magnitude), 2),
                           "decimalPlaces": 2})
            states.append({"key": "last_strike_energy", "value": int(event.energy)})
        if states:
            dev.updateStatesOnServer(states)

    def _on_rain_start(self, device: WeatherFlowSensorDevice, event: Any) -> None:
        dev = self._get_indigo_dev(device.serial_number)
        if dev is None:
            return
        if event is not None:
            ts = str(event.timestamp) if event.timestamp else ""
            dev.updateStateOnServer("last_rain_start", ts)

    def _on_hub_status(self, device: HubDevice) -> None:
        dev = self._get_indigo_dev(device.serial_number)
        if dev is None:
            return
        states: list[dict] = []
        if device.firmware_revision:
            states.append({"key": "firmware_revision",
                           "value": str(device.firmware_revision)})
        _add_int(states, "rssi", device.rssi)
        if device.up_since:
            states.append({"key": "up_since", "value": str(device.up_since)})
        if device.uptime is not None:
            _add_int(states, "uptime", device.uptime)
        if device.reset_flags is not None:
            states.append({"key": "reset_flags",
                           "value": ", ".join(device.reset_flags)})
        if states:
            dev.updateStatesOnServer(states)

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
        sn = device.pluginProps.get("serialNumber", "").strip()
        if not sn:
            self.logger.warning("%s: no serial number configured", device.name)
            return

        self._serial_to_dev_id[sn] = device.id
        device.updateStateOnServer("deviceStatus", "Waiting for data")
        self.logger.info("%s (%s): comm started", device.name, sn)

        # If already discovered before this device was configured, subscribe now
        wf_dev = self._discovered.get(sn)
        if wf_dev is not None and sn not in self._unsubs:
            if isinstance(wf_dev, WeatherFlowSensorDevice):
                self._subscribe_sensor(wf_dev)
                # Push any already-received data immediately
                altitude_qty = self._get_altitude(device)
                states = _build_observation_states(wf_dev, altitude_qty)
                states.extend(_build_status_states(wf_dev))
                if states:
                    device.updateStatesOnServer(states)
            elif isinstance(wf_dev, HubDevice):
                self._subscribe_hub(wf_dev)

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
                self.logger.setLevel(self.logLevel)
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
        """Dynamic list callback — shows discovered WeatherFlow devices filtered by device type."""
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
    # Plugin config UI — device generation
    # -------------------------------------------------------------------------

    def generateDevices(self, valuesDict=None, typeId=""):
        """Create Indigo devices for all discovered WeatherFlow sensors and hubs."""
        if not self._discovered:
            self.logger.warning(
                "No WeatherFlow devices discovered yet. "
                "Ensure the hub is on, on the same subnet, and UDP port %d is reachable.",
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
                self.logger.debug("  %s: unknown prefix, skipping", sn)
                continue

            dev_name = f"WeatherFlow {wf_dev.model} {sn}"
            props = {"serialNumber": sn, "altitude": "0"}

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
                "Generated %d new Indigo device(s) from %d discovered.",
                created,
                len(self._discovered),
            )
        return valuesDict

    # -------------------------------------------------------------------------
    # Menu items
    # -------------------------------------------------------------------------

    def menuListDiscoveredDevices(self):
        if not self._discovered:
            self.logger.info(
                "No WeatherFlow devices discovered yet. "
                "Ensure the hub is on the same subnet and UDP port %d is not blocked.",
                int(self.pluginPrefs.get("udpPort", DEFAULT_PORT)),
            )
            return
        self.logger.info("Discovered WeatherFlow devices (%d):", len(self._discovered))
        for sn, dev in self._discovered.items():
            fw = dev.firmware_revision
            self.logger.info("  %s  model=%-8s  firmware=%s", sn, dev.model, fw)

    def menuRestartListener(self):
        self.logger.info("WeatherFlow: manually restarting UDP listener")
        if self._event_loop:
            asyncio.run_coroutine_threadsafe(
                self._restart_listener(), self._event_loop
            )


# =============================================================================
# State builder functions (module-level, no self needed)
# =============================================================================

def _build_observation_states(
    device: WeatherFlowSensorDevice, altitude_qty: Any = None
) -> list[dict]:
    states: list[dict] = []

    # --- Temperature ---
    _add_float(states, "air_temperature", device.air_temperature, 1)
    _add_float(states, "dew_point_temperature", device.dew_point_temperature, 1)
    _add_float(states, "wet_bulb_temperature", device.wet_bulb_temperature, 1)
    _add_float(states, "heat_index", device.heat_index, 1)
    _add_float(states, "delta_t", device.delta_t, 1)

    if isinstance(device, TempestDevice):
        _add_float(states, "feels_like_temperature", device.feels_like_temperature, 1)
        _add_float(states, "wind_chill_temperature", device.wind_chill_temperature, 1)

    # --- Atmospheric ---
    _add_float(states, "relative_humidity", device.relative_humidity, 0)
    _add_float(states, "station_pressure", device.station_pressure, 2)
    _add_float(states, "vapor_pressure", device.vapor_pressure, 2)
    _add_float(states, "air_density", device.air_density, 5)

    if altitude_qty is not None:
        try:
            _add_float(
                states,
                "sea_level_pressure",
                device.calculate_sea_level_pressure(altitude_qty),
                2,
            )
        except Exception:
            pass

    # --- Light / UV ---
    _add_int(states, "illuminance", device.illuminance)
    _add_int(states, "solar_radiation", device.solar_radiation)
    _add_float(states, "uv", device.uv, 1)

    # --- Rain ---
    _add_float(
        states,
        "rain_accumulation_previous_minute",
        device.rain_accumulation_previous_minute,
        2,
    )
    _add_float(states, "rain_rate", device.rain_rate, 2)
    if device.precipitation_type is not None:
        name = device.precipitation_type.name.lower()
        states.append({"key": "precipitation_type", "value": name})

    # --- Lightning ---
    if device.lightning_strike_count is not None:
        states.append(
            {"key": "lightning_strike_count", "value": device.lightning_strike_count}
        )
    _add_float(
        states,
        "lightning_strike_average_distance",
        device.lightning_strike_average_distance,
        2,
    )

    # --- Wind (from observation; rapid-wind handler overlays live speed) ---
    states.extend(_build_wind_states(device))

    # --- Battery ---
    _add_float(states, "battery", device.battery, 2)
    _add_float(states, "battery_percent", device.battery_percent, 0)

    # --- Timestamp ---
    if device.last_report:
        states.append({"key": "last_report", "value": str(device.last_report)})

    if isinstance(device, TempestDevice):
        psm = device.power_save_mode
        states.append({"key": "power_save_mode", "value": psm.name})

    states.append({"key": "deviceStatus", "value": "Active"})
    return states


def _build_wind_states(device: WeatherFlowSensorDevice) -> list[dict]:
    states: list[dict] = []
    _add_float(states, "wind_speed", device.wind_speed, 2)
    _add_float(states, "wind_average", device.wind_average, 2)
    _add_float(states, "wind_gust", device.wind_gust, 2)
    _add_float(states, "wind_lull", device.wind_lull, 2)
    _add_float(states, "wind_direction", device.wind_direction, 0)
    _add_float(states, "wind_direction_average", device.wind_direction_average, 0)
    cardinal = device.wind_direction_cardinal
    if cardinal:
        states.append({"key": "wind_direction_cardinal", "value": cardinal})
    return states


def _build_status_states(device: WeatherFlowSensorDevice) -> list[dict]:
    states: list[dict] = []
    _add_int(states, "rssi", device.rssi)
    _add_int(states, "hub_rssi", device.hub_rssi)
    if device.firmware_revision:
        states.append({"key": "firmware_revision", "value": str(device.firmware_revision)})
    if device.hub_sn:
        states.append({"key": "hub_sn", "value": str(device.hub_sn)})
    if device.up_since:
        states.append({"key": "up_since", "value": str(device.up_since)})
    sensor_status = device.sensor_status
    if sensor_status is not None:
        status_str = ", ".join(sensor_status) if sensor_status else "OK"
        states.append({"key": "sensor_status", "value": status_str})
    return states


def _add_float(states: list[dict], key: str, value: Any, decimal_places: int) -> None:
    if value is None:
        return
    try:
        mag = value.magnitude if hasattr(value, "magnitude") else value
        states.append(
            {
                "key": key,
                "value": round(float(mag), decimal_places),
                "decimalPlaces": decimal_places,
            }
        )
    except (TypeError, AttributeError, ValueError):
        pass


def _add_int(states: list[dict], key: str, value: Any) -> None:
    if value is None:
        return
    try:
        mag = value.magnitude if hasattr(value, "magnitude") else value
        states.append({"key": key, "value": int(mag)})
    except (TypeError, AttributeError, ValueError):
        pass
