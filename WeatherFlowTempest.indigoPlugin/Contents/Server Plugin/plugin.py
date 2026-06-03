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
import datetime
import json
import logging
import math
import threading
import time
import urllib.request
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

# Pint unit for manual quantity construction (e.g. wrapping a plain float as mm)
_UNIT_MM = units.mm

_WEB_API_BASE = "https://swd.weatherflow.com/swd/rest"
_PUBLIC_API_KEY = "6bff2f89-84ab-463c-886e-fc0f443da4cf"
_PUBLIC_HEADERS = {
    "Origin":     "https://tempestwx.com",
    "Referer":    "https://tempestwx.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
# Mappings from pluginProp unit values → WeatherFlow API query parameter values
_UNIT_PREFS_TO_API_TEMP     = {"celsius": "c",     "fahrenheit": "f"}
_UNIT_PREFS_TO_API_WIND     = {"ms": "ms",         "kmh": "kph",  "knots": "kts", "mph": "mph"}
_UNIT_PREFS_TO_API_PRESSURE = {"hpa": "hpa",       "mmhg": "mmhg",  "inhg": "inhg"}
_UNIT_PREFS_TO_API_RAIN     = {"mm": "mm",         "inch": "in"}

_RAIN_CHECK_LABELS: dict[int, str] = {0: "none", 1: "on", 2: "off"}


def _patch_tempest_device() -> None:
    """Expose obs_st extended indices (18, 21) without modifying library files.

    pyweatherflowudp's OBSERVATION_VALUES_MAP stops at index 17. We wrap parse_observation
    to capture:
      - Index 18: local daily rain accumulation (resets at hub local midnight)
      - Index 21: precipitation_analysis_type (WeatherFlow Rain Check status: 0=none/1=on/2=off)
    Indices 19/20 are rain-check corrected rain values — used as daily-rain fallback only.

    The one-time diagnostic log uses an instance attribute (_obs_packet_logged) on the
    TempestDevice object rather than a closure variable. The closure approach fails because
    the class persists in sys.modules across plugin reloads, keeping the closure flag True
    permanently and silencing the log. Instance attributes reset naturally with each new
    device object that the listener creates on restart.
    """
    try:
        from pyweatherflowudp.device import TempestDevice
        from pyweatherflowudp.const import UNIT_MILLIMETERS
        from pyweatherflowudp.helpers import value_as_unit

        if hasattr(TempestDevice, "local_daily_rain_accumulation"):
            return  # already patched (plugin reload without process restart)

        _orig_parse = TempestDevice.parse_observation
        _log = logging.getLogger("Plugin.patch_tempest")

        def _parse_observation_extended(self, data: list) -> None:  # type: ignore[override]
            _orig_parse(self, data)
            for observation in data:
                n = len(observation)

                # Log raw packet once per device instance to verify which indices are present.
                # Stored on the instance so it resets when the listener creates a new device
                # object, unlike a closure variable which persists across plugin reloads.
                if not getattr(self, "_obs_packet_logged", False):
                    self._obs_packet_logged = True
                    _log.debug(
                        "obs_st raw packet: len=%d  full=%s", n, observation
                    )
                    _log.debug(
                        "obs_st extended indices: [18]=%s [19]=%s [20]=%s [21]=%s",
                        observation[18] if n > 18 else "absent",
                        observation[19] if n > 19 else "absent",
                        observation[20] if n > 20 else "absent",
                        observation[21] if n > 21 else "absent",
                    )

                # Index 18: local daily rain accumulation (resets at hub local midnight).
                # Confirmed correct across firmware versions. Indices 19/20 are corrected
                # rain-check variants present in later firmware — used as fallback only.
                if n > 18 and observation[18] is not None:
                    self._local_daily_rain_accumulation = observation[18]
                elif n > 20 and observation[20] is not None:
                    self._local_daily_rain_accumulation = observation[20]
                elif n > 19 and observation[19] is not None:
                    self._local_daily_rain_accumulation = observation[19]

                # Index 21: precipitation analysis type (WeatherFlow Rain Check).
                # 0 = none (no rain / not configured), 1 = on (verified), 2 = off (opted out).
                if n > 21 and observation[21] is not None:
                    self._precipitation_analysis_type_raw = int(observation[21])

        TempestDevice.parse_observation = _parse_observation_extended  # type: ignore[method-assign]

        TempestDevice.local_daily_rain_accumulation = property(  # type: ignore[attr-defined]
            lambda self: value_as_unit(
                getattr(self, "_local_daily_rain_accumulation", None),
                UNIT_MILLIMETERS,
            )
        )
        TempestDevice.rain_check = property(  # type: ignore[attr-defined]
            lambda self: _RAIN_CHECK_LABELS.get(
                getattr(self, "_precipitation_analysis_type_raw", 0), "none"
            )
        )
        _log.debug(
            "TempestDevice patched: obs_st index 18 → local_daily_rain_accumulation, "
            "index 21 → rain_check"
        )
    except Exception as ex:
        logging.getLogger(__name__).warning(
            "Could not extend TempestDevice for daily rain / rain check: %s", ex
        )


def _patch_sky_device() -> None:
    """Expose obs_sky extended indices (11, 16) on SkyDevice without modifying library files.

    SkyDevice's OBSERVATION_VALUES_MAP stops at index 13. The obs_sky packet contains:
      - Index 11: local daily rain accumulation (mm, resets at hub local midnight)
      - Index 14: rain_accumulated_final (rain-check corrected)
      - Index 15: daily_rain_accumulation_final (rain-check corrected)
      - Index 16: precipitation_analysis_type (Rain Check: 0=none, 1=on, 2=off)

    These are the Sky equivalents of the Tempest's indices 18 and 21.
    """
    try:
        from pyweatherflowudp.device import SkyDevice
        from pyweatherflowudp.const import UNIT_MILLIMETERS
        from pyweatherflowudp.helpers import value_as_unit

        if hasattr(SkyDevice, "local_daily_rain_accumulation"):
            return

        _orig_parse = SkyDevice.parse_observation
        _log = logging.getLogger("Plugin.patch_sky")

        def _parse_sky_extended(self, data: list) -> None:  # type: ignore[override]
            _orig_parse(self, data)
            for observation in data:
                n = len(observation)

                if not getattr(self, "_obs_packet_logged", False):
                    self._obs_packet_logged = True
                    _log.debug("obs_sky raw packet: len=%d  full=%s", n, observation)
                    _log.debug(
                        "obs_sky extended indices: [11]=%s [14]=%s [15]=%s [16]=%s",
                        observation[11] if n > 11 else "absent",
                        observation[14] if n > 14 else "absent",
                        observation[15] if n > 15 else "absent",
                        observation[16] if n > 16 else "absent",
                    )

                # Index 11: daily rain for Sky (same role as index 18 for Tempest).
                if n > 11 and observation[11] is not None:
                    self._local_daily_rain_accumulation = observation[11]
                elif n > 15 and observation[15] is not None:
                    self._local_daily_rain_accumulation = observation[15]
                elif n > 14 and observation[14] is not None:
                    self._local_daily_rain_accumulation = observation[14]

                # Index 16: precipitation analysis type (Rain Check).
                if n > 16 and observation[16] is not None:
                    self._precipitation_analysis_type_raw = int(observation[16])

        SkyDevice.parse_observation = _parse_sky_extended  # type: ignore[method-assign]

        SkyDevice.local_daily_rain_accumulation = property(  # type: ignore[attr-defined]
            lambda self: value_as_unit(
                getattr(self, "_local_daily_rain_accumulation", None),
                UNIT_MILLIMETERS,
            )
        )
        SkyDevice.rain_check = property(  # type: ignore[attr-defined]
            lambda self: _RAIN_CHECK_LABELS.get(
                getattr(self, "_precipitation_analysis_type_raw", 0), "none"
            )
        )
        _log.debug(
            "SkyDevice patched: obs_sky index 11 → local_daily_rain_accumulation, "
            "index 16 → rain_check"
        )
    except Exception as ex:
        logging.getLogger(__name__).warning(
            "Could not extend SkyDevice for daily rain / rain check: %s", ex
        )


_CARDINALS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def _degrees_to_cardinal(degrees: float) -> str:
    return _CARDINALS[round(degrees / 22.5) % 16]


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
        # serial_number -> epoch of last silence warning (throttles repeat logs)
        self._silence_warned: dict[str, float] = {}
        # serial_number -> ISO date of last observation (midnight-rollover detection)
        self._rain_date: dict[str, str] = {}
        # serial_number -> WeatherFlow station_id (discovered via REST /stations)
        self._station_id_map: dict[str, int] = {}
        self._web_poll_task: asyncio.Task | None = None
        # station_id -> consecutive poll failure count (resets on success; suspends at 3)
        self._station_fail_count: dict[int, int] = {}
        # Public station poller (separate task, no personal token)
        self._public_poll_task: asyncio.Task | None = None
        self._public_fail_count: dict[int, int] = {}
        # dev_id -> epoch when data first became stale (cleared on good update)
        self._web_stale_since: dict[int, float] = {}

    # -------------------------------------------------------------------------
    # Plugin lifecycle
    # -------------------------------------------------------------------------

    def startup(self) -> None:
        self.logger.info("WeatherFlow Tempest: starting")
        _patch_tempest_device()
        _patch_sky_device()

        self._event_loop = asyncio.new_event_loop()
        self._async_thread = threading.Thread(
            target=self._event_loop.run_forever,
            daemon=True,
            name="WeatherFlowEventLoop",
        )
        self._async_thread.start()

        for dev in indigo.devices.iter("self"):
            if not dev.pluginProps.get("webOnly", False):
                sn = dev.pluginProps.get("serialNumber", "").strip()
                if sn:
                    self._serial_to_dev_id[sn] = dev.id

        asyncio.run_coroutine_threadsafe(self._start_listener(), self._event_loop)
        self._start_web_poller()
        self._start_public_poller()

    def shutdown(self) -> None:
        self.logger.info("WeatherFlow Tempest: shutting down")
        loop = self._event_loop
        if loop and loop.is_running():
            # Cancel the UDP socket task directly (synchronous, no coroutine needed)
            # then stop the loop. Using call_soon_threadsafe avoids any await that
            # could race with loop.stop() and cause a hang.
            if self._listener:
                udp_task = getattr(self._listener, "_udp_task", None)
                if udp_task and not udp_task.done():
                    loop.call_soon_threadsafe(udp_task.cancel)
            if self._web_poll_task and not self._web_poll_task.done():
                loop.call_soon_threadsafe(self._web_poll_task.cancel)
            if self._public_poll_task and not self._public_poll_task.done():
                loop.call_soon_threadsafe(self._public_poll_task.cancel)
            loop.call_soon_threadsafe(loop.stop)

    def runConcurrentThread(self) -> None:
        try:
            while True:
                self.sleep(60)
                if not self._event_loop:
                    continue

                # Restart listener if the UDP socket task has crashed
                udp_task = getattr(self._listener, "_udp_task", None) if self._listener else None
                listener_dead = (
                    self._listener is None
                    or not self._listener.is_listening
                    or (udp_task is not None and udp_task.done())
                )
                if listener_dead:
                    self.logger.warning("WeatherFlow UDP listener stopped unexpectedly — restarting")
                    asyncio.run_coroutine_threadsafe(
                        self._restart_listener(), self._event_loop
                    )
                    continue

                # Restart web poller if it exited unexpectedly (e.g. unhandled exception)
                if (
                    self.pluginPrefs.get("useWebData", False)
                    and self.pluginPrefs.get("apiToken", "").strip()
                    and (self._web_poll_task is None or self._web_poll_task.done())
                ):
                    self.logger.warning("WeatherFlow web API poller stopped — restarting")
                    self._start_web_poller()

                # Restart public poller if it crashed and public devices exist
                if self._public_poll_task is not None and self._public_poll_task.done():
                    has_public = any(
                        d.deviceTypeId == "publicTempestStation"
                        for d in indigo.devices.iter("self")
                    )
                    if has_public:
                        self.logger.warning("WeatherFlow public station poller stopped — restarting")
                        self._start_public_poller()

                # Heartbeat: detect stations that have gone silent
                now = time.time()
                for sn, dev_id in list(self._serial_to_dev_id.items()):
                    wf_dev = self._discovered.get(sn)
                    if wf_dev is None:
                        continue
                    last = getattr(wf_dev, "_last_report", None)
                    if not last:
                        continue
                    silent_secs = now - last
                    if silent_secs <= 300:
                        # Data is flowing — clear any prior silence state
                        if sn in self._silence_warned:
                            del self._silence_warned[sn]
                        continue
                    # Station has been silent > 5 minutes
                    silent_mins = int(silent_secs / 60)
                    last_warned = self._silence_warned.get(sn, 0)
                    warn_interval = 1800 if last_warned else 0  # first warn immediately, then every 30 min
                    if (now - last_warned) >= warn_interval:
                        self._silence_warned[sn] = now
                        self.logger.warning(
                            "%s: no observation received for %d minutes",
                            sn, silent_mins,
                        )
                        try:
                            dev = indigo.devices[dev_id]
                            dev.updateStateOnServer(
                                "deviceStatus",
                                f"No data — last seen {silent_mins} min ago",
                            )
                        except Exception:
                            pass
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
        # Give the event loop time to process the transport.close() callback and
        # release the OS socket. Without this yield, the port is still bound when
        # we call create_datagram_endpoint and we get "Address already in use".
        await asyncio.sleep(2)
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
        if sn in self._discovered:
            return  # pyweatherflowudp can fire this event more than once per device
        self._discovered[sn] = device
        self.logger.info("Discovered WeatherFlow device: %s  model=%s", sn, device.model)

        # If the Indigo device is configured as web-only, skip UDP subscriptions
        # entirely — all state updates come from the web API instead.
        indigo_dev = self._get_indigo_dev(sn)
        if indigo_dev is not None and indigo_dev.pluginProps.get("webOnly", False):
            self.logger.debug("%s: web-only — skipping UDP event subscriptions", sn)
            return

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
            self._log_startup_snapshot(device)
        except Exception:
            self.logger.exception("%s: error in load-complete handler", device.serial_number)

    def _log_startup_snapshot(self, device: WeatherFlowSensorDevice) -> None:
        """Log a full sensor snapshot at DEBUG level for startup diagnostics."""
        if not self.logger.isEnabledFor(logging.DEBUG):
            return
        sn = device.serial_number
        dev = self._get_indigo_dev(sn)
        unit_prefs = _get_unit_prefs(dev) if dev else {}
        altitude_qty = self._get_altitude(dev) if dev else None

        def _fmt(qty) -> str:
            if qty is None:
                return "None"
            mag = qty.magnitude if hasattr(qty, "magnitude") else qty
            unit = f" {qty.units}" if hasattr(qty, "units") else ""
            return f"{mag}{unit}"

        self.logger.debug("%s: --- startup snapshot ---", sn)
        self.logger.debug("%s:   unit prefs: %s", sn, unit_prefs)
        self.logger.debug("%s:   model=%s  firmware=%s  hub_sn=%s",
                          sn, device.model, device.firmware_revision, device.hub_sn)
        self.logger.debug("%s:   up_since=%s  last_report=%s",
                          sn, device.up_since, device.last_report)
        self.logger.debug("%s:   battery=%s  battery_percent=%s  power_save_mode=%s",
                          sn, _fmt(device.battery),
                          _fmt(device.battery_percent),
                          getattr(device, "power_save_mode", None))
        self.logger.debug("%s:   air_temp=%s  dew_point=%s  wet_bulb=%s",
                          sn, _fmt(getattr(device, "air_temperature", None)),
                          _fmt(getattr(device, "dew_point_temperature", None)),
                          _fmt(getattr(device, "wet_bulb_temperature", None)))
        self.logger.debug("%s:   heat_index=%s  delta_t=%s",
                          sn, _fmt(getattr(device, "heat_index", None)),
                          _fmt(getattr(device, "delta_t", None)))
        if isinstance(device, TempestDevice):
            self.logger.debug("%s:   feels_like=%s  wind_chill=%s",
                              sn, _fmt(device.feels_like_temperature),
                              _fmt(device.wind_chill_temperature))
        self.logger.debug("%s:   humidity=%s  station_pressure=%s  vapor_pressure=%s",
                          sn, _fmt(getattr(device, "relative_humidity", None)),
                          _fmt(getattr(device, "station_pressure", None)),
                          _fmt(getattr(device, "vapor_pressure", None)))
        self.logger.debug("%s:   air_density=%s", sn, _fmt(getattr(device, "air_density", None)))
        if altitude_qty is not None:
            try:
                self.logger.debug("%s:   altitude=%s  sea_level_pressure=%s  cloud_base=%s  freezing_level=%s",
                                  sn, _fmt(altitude_qty),
                                  _fmt(device.calculate_sea_level_pressure(altitude_qty)),
                                  _fmt(device.calculate_cloud_base(altitude_qty)),
                                  _fmt(device.calculate_freezing_level(altitude_qty)))
            except Exception:
                pass
        self.logger.debug("%s:   illuminance=%s  solar_radiation=%s  uv=%s",
                          sn, _fmt(getattr(device, "illuminance", None)),
                          _fmt(getattr(device, "solar_radiation", None)),
                          _fmt(getattr(device, "uv", None)))
        self.logger.debug("%s:   rain_accum_prev_min=%s  rain_rate=%s  precip_type=%s",
                          sn, _fmt(getattr(device, "rain_accumulation_previous_minute", None)),
                          _fmt(getattr(device, "rain_rate", None)),
                          getattr(device, "precipitation_type", None))
        self.logger.debug("%s:   local_daily_rain_accumulation=%s  _raw_idx18=%s",
                          sn,
                          _fmt(getattr(device, "local_daily_rain_accumulation", None)),
                          getattr(device, "_local_daily_rain_accumulation", "NOT SET"))
        self.logger.debug("%s:   wind_speed=%s  wind_avg=%s  wind_gust=%s  wind_lull=%s",
                          sn, _fmt(getattr(device, "wind_speed", None)),
                          _fmt(getattr(device, "wind_average", None)),
                          _fmt(getattr(device, "wind_gust", None)),
                          _fmt(getattr(device, "wind_lull", None)))
        self.logger.debug("%s:   wind_dir=%s  wind_dir_avg=%s  cardinal=%s  cardinal_avg=%s",
                          sn, _fmt(getattr(device, "wind_direction", None)),
                          _fmt(getattr(device, "wind_direction_average", None)),
                          getattr(device, "wind_direction_cardinal", None),
                          getattr(device, "wind_direction_average_cardinal", None))
        self.logger.debug("%s:   lightning_count=%s  lightning_avg_dist=%s",
                          sn, getattr(device, "lightning_strike_count", None),
                          _fmt(getattr(device, "lightning_strike_average_distance", None)))
        self.logger.debug("%s:   rssi=%s  hub_rssi=%s  sensor_status_raw=0x%X",
                          sn, device.rssi, device.hub_rssi,
                          getattr(device, "_sensor_status", 0) or 0)
        # Show the converted states that were actually pushed to Indigo
        states = _build_observation_states(device, altitude_qty, unit_prefs)
        self.logger.debug("%s:   converted states pushed to Indigo:", sn)
        for s in states:
            self.logger.debug("%s:     %s = %s  (uiValue=%s)",
                              sn, s["key"], s.get("value"), s.get("uiValue", ""))

    def _on_observation(self, device: WeatherFlowSensorDevice) -> None:
        try:
            sn = device.serial_number
            dev = self._get_indigo_dev(sn)
            if dev is None:
                return

            # Silence recovery
            if sn in self._silence_warned:
                del self._silence_warned[sn]
                self.logger.info("%s: data resumed", sn)

            # Midnight rollover: capture yesterday's total and reset the accumulator.
            # Must run before we read rain_today_raw_mm for accumulation below.
            today_str = datetime.date.today().isoformat()
            rain_yesterday_mm: float | None = None
            prev_date = self._rain_date.get(sn)
            is_new_day = False

            if prev_date is None:
                # First observation this session — check if the day changed since we last ran
                stored_date = ""
                try:
                    stored_date = str(dev.states.get("rain_today_date", ""))
                except Exception:
                    pass
                if stored_date and stored_date != today_str:
                    try:
                        rain_yesterday_mm = float(dev.states.get("rain_today_local_raw_mm", 0.0) or 0.0)
                    except Exception:
                        rain_yesterday_mm = 0.0
                    is_new_day = True
                    self.logger.info(
                        "%s: new day since last run (%s → %s), yesterday rain=%.2f mm",
                        sn, stored_date, today_str, rain_yesterday_mm,
                    )
                self._rain_date[sn] = today_str
            elif prev_date != today_str:
                # Day rolled over while the plugin was running
                try:
                    rain_yesterday_mm = float(dev.states.get("rain_today_local_raw_mm", 0.0) or 0.0)
                except Exception:
                    rain_yesterday_mm = 0.0
                is_new_day = True
                self.logger.info(
                    "%s: new day (%s → %s), yesterday rain=%.2f mm",
                    sn, prev_date, today_str, rain_yesterday_mm,
                )
                self._rain_date[sn] = today_str

            # Daily rain: Sky-type devices only (Sky, Tempest). Air has no rain sensor.
            # Prefer the hub's index 18 value (authoritative, resets at local midnight).
            # In power-save modes (e.g. MODE_2 with low battery) the Tempest sends shorter
            # obs_st packets (18 elements, indices 0-17 only) that omit index 18. In that
            # case we fall back to accumulating the per-minute rain_accumulated values
            # (index 12) ourselves — less precise on restart but correct otherwise.
            rain_today_mm: float | None = None
            rain_source = "n/a"

            if isinstance(device, SkySensorType):
                daily_qty = getattr(device, "local_daily_rain_accumulation", None)
                rain_today_mm = (
                    float(daily_qty.magnitude)
                    if daily_qty is not None and hasattr(daily_qty, "magnitude")
                    else None
                )
                rain_source = "hub"

                if rain_today_mm is None:
                    # Index 18 absent — accumulate from per-minute values.
                    # Use rain_today_local_raw_mm as the baseline so the web API
                    # writing to rain_today_raw_mm cannot corrupt the running total.
                    rain_prev_min = getattr(device, "rain_accumulation_previous_minute", None)
                    rain_prev_min_mm = (
                        float(rain_prev_min.magnitude)
                        if rain_prev_min is not None and hasattr(rain_prev_min, "magnitude")
                        else 0.0
                    )
                    if is_new_day:
                        prior_mm = 0.0
                    else:
                        try:
                            prior_mm = float(dev.states.get("rain_today_local_raw_mm", 0.0) or 0.0)
                        except Exception:
                            prior_mm = 0.0
                    rain_today_mm = prior_mm + rain_prev_min_mm
                    rain_source = "accumulated"

            # --- Build and push states ---
            altitude_qty = self._get_altitude(dev)
            unit_prefs = _get_unit_prefs(dev)
            states = _build_observation_states(
                device, altitude_qty, unit_prefs,
                rain_today_mm=rain_today_mm,
                rain_yesterday_mm=rain_yesterday_mm,
                rain_source=rain_source,
            )
            if states:
                self._safe_update_states(dev, states)

            _t = getattr(device, "air_temperature", None)
            _h = getattr(device, "relative_humidity", None)
            _p = getattr(device, "station_pressure", None)
            _r = getattr(device, "rain_rate", None)
            _hi = getattr(device, "heat_index", None)
            self.logger.debug(
                "%s: observation  temp=%s  humidity=%s  pressure=%s  rain_rate=%s  rain_today=%s mm (%s)  heat_index=%s",
                sn,
                getattr(_t, "magnitude", _t),
                getattr(_h, "magnitude", _h),
                getattr(_p, "magnitude", _p),
                getattr(_r, "magnitude", _r),
                f"{rain_today_mm:.2f}" if rain_today_mm is not None else "n/a",
                rain_source,
                getattr(_hi, "magnitude", _hi),
            )
            if isinstance(device, TempestDevice):
                _wc = device.wind_chill_temperature
                _fl = device.feels_like_temperature
                self.logger.debug(
                    "%s:   wind_chill=%s  feels_like=%s  delta_t=%s",
                    sn,
                    getattr(_wc, "magnitude", _wc),
                    getattr(_fl, "magnitude", _fl),
                    getattr(getattr(device, "delta_t", None), "magnitude",
                            getattr(device, "delta_t", None)),
                )
        except Exception:
            self.logger.exception("%s: error in observation handler", device.serial_number)

    def _on_status_update(self, device: WeatherFlowSensorDevice) -> None:
        try:
            dev = self._get_indigo_dev(device.serial_number)
            if dev is None:
                return
            self.logger.debug(
                "%s: sensor_status raw=0x%X decoded=%s",
                device.serial_number,
                getattr(device, "_sensor_status", -1),
                device.sensor_status or "OK",
            )
            states = _build_status_states(device)
            if states:
                self._safe_update_states(dev, states)
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
                self._safe_update_states(dev, states)
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
                if event.timestamp:
                    states.append({"key": "last_strike_time", "value": str(event.timestamp)})
            if states:
                self._safe_update_states(dev, states)
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
                self._safe_update_states(dev, states)
        except Exception:
            self.logger.exception("%s: error in hub-status handler", device.serial_number)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _safe_update_states(self, dev, states: list[dict]) -> None:
        """Write states to an Indigo device, auto-registering any missing keys first.

        Dynamic states (created by strike events, first UDP observation, etc.) may
        not yet be registered on a device that was offline at startup or has just
        recovered. This helper:

        1. Checks whether every key in `states` is present in dev.states.
        2. If any are absent, calls stateListOrDisplayStateIdChanged() so Indigo
           re-reads Devices.xml and registers any newly-defined states.
        3. Re-fetches the device so dev.states is current.
        4. Filters out keys that are *still* absent after the sync (these are
           legacy state names from an older plugin version that no longer exist
           in Devices.xml — they cannot be written and the errors are suppressed).
        5. Calls updateStatesOnServer with the valid, filtered list.
        """
        missing = [s["key"] for s in states if s["key"] not in dev.states]
        if missing:
            self.logger.debug(
                "%s: state keys not yet registered %s — refreshing state list",
                dev.name, missing,
            )
            dev.stateListOrDisplayStateIdChanged()
            dev = indigo.devices.get(dev.id)
            if dev is None:
                return
            still_missing = [k for k in missing if k not in dev.states]
            if still_missing:
                self.logger.debug(
                    "%s: skipping %d legacy/undefined state(s): %s",
                    dev.name, len(still_missing), still_missing,
                )
            states = [s for s in states if s["key"] in dev.states]
        if states:
            dev.updateStatesOnServer(states)

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

        # Clear any error state left over from a previous run (e.g. plugin crash,
        # station offline at last shutdown). Each device path sets it fresh if needed.
        device.setErrorStateOnServer(None)
        self._web_stale_since.pop(device.id, None)

        # Public station: polls the WeatherFlow public API, no personal token needed.
        if device.deviceTypeId == "publicTempestStation":
            station_id_str = device.pluginProps.get("stationId", "").strip()
            if not station_id_str or not station_id_str.isdigit():
                self.logger.warning("%s: public station requires a numeric station ID", device.name)
                return
            station_id = int(station_id_str)
            self._public_fail_count.pop(station_id, None)  # reset any prior suspension
            device.updateStateOnServer("deviceStatus", "Waiting for data")
            self.logger.info("%s: public station comm started, station_id=%d", device.name, station_id)
            self._start_public_poller()
            return

        # Web-only mode: station ID entered manually; no UDP discovery.
        # The web poller iterates Indigo devices directly and populates all states.
        if device.pluginProps.get("webOnly", False):
            station_id_str = device.pluginProps.get("stationId", "").strip()
            if not station_id_str:
                self.logger.warning("%s: web-only mode requires a station ID", device.name)
                return
            try:
                station_id = int(station_id_str)
            except (ValueError, TypeError):
                self.logger.warning("%s: invalid station ID %r", device.name, station_id_str)
                return
            device.updateStateOnServer("deviceStatus", "Waiting for web data")
            self.logger.info("%s: web-only comm started, station_id=%d", device.name, station_id)
            return

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
                    self._safe_update_states(device, states)
            elif isinstance(wf_dev, HubDevice):
                self._on_hub_status(wf_dev)

    def deviceStopComm(self, device) -> None:
        if device.deviceTypeId == "publicTempestStation":
            self.logger.info("%s: public station comm stopped", device.name)
            return
        if not device.pluginProps.get("webOnly", False):
            sn = device.pluginProps.get("serialNumber", "").strip()
            if sn:
                self._unsubscribe(sn)
                self._serial_to_dev_id.pop(sn, None)
                self._station_id_map.pop(sn, None)
        self.logger.info("%s: comm stopped", device.name)

    # -------------------------------------------------------------------------
    # Plugin config UI
    # -------------------------------------------------------------------------

    def validatePrefsConfigUi(self, valuesDict):
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

    def closedPrefsConfigUi(self, valuesDict, userCancelled) -> None:
        if userCancelled:
            return
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
        self.logger.info("WeatherFlow: preferences saved — restarting UDP listener")
        if self._event_loop:
            asyncio.run_coroutine_threadsafe(
                self._restart_listener(), self._event_loop
            )
        self._start_web_poller()


    # -------------------------------------------------------------------------
    # Device config UI
    # -------------------------------------------------------------------------

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        errors = indigo.Dict()
        if typeId == "publicTempestStation":
            station_id = valuesDict.get("stationId", "").strip()
            if not station_id:
                errors["stationId"] = (
                    "Enter the station ID from the tempestwx.com URL "
                    "(e.g. tempestwx.com/station/130809/ → 130809)"
                )
            elif not station_id.isdigit():
                errors["stationId"] = "Station ID must be a number (e.g. 130809)"
        elif valuesDict.get("webOnly", False):
            station_id = valuesDict.get("stationId", "").strip()
            if not station_id:
                errors["stationId"] = (
                    "Enter your WeatherFlow station ID (WeatherFlow app → station Settings)"
                )
            elif not station_id.isdigit():
                errors["stationId"] = "Station ID must be a number (e.g. 12345)"
        else:
            sn = valuesDict.get("serialNumber", "").strip()
            if not sn or sn.startswith("__"):
                errors["serialNumber"] = (
                    "No device selected. Wait for discovery or check hub is on the same network."
                )
        if errors:
            return False, valuesDict, errors
        return True, valuesDict, errors

    def getDiscoveredDeviceList(self, filter="", valuesDict=None, typeId="", targetId=0):
        items = []
        for sn, dev in self._discovered.items():
            if typeId == "tempestStation" and not sn.startswith("ST"):
                continue
            if typeId == "hubStation" and not sn.startswith("HB"):
                continue
            if typeId == "skyStation" and not sn.startswith("SK"):
                continue
            if typeId == "airStation" and not sn.startswith("AR"):
                continue
            items.append((sn, f"{sn}  ({dev.model})"))
        if not items:
            items.append(("__none__", "── No devices discovered yet ──"))
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
            elif sn.startswith("SK"):
                dev_type_id = "skyStation"
            elif sn.startswith("AR"):
                dev_type_id = "airStation"
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

    # -------------------------------------------------------------------------
    # Web API — polling and state update
    # -------------------------------------------------------------------------

    def _start_web_poller(self) -> None:
        """Start (or restart) the background web API polling task."""
        loop = self._event_loop
        # Always cancel any running task first (handles checkbox being unchecked).
        # Sets _web_poll_task to None synchronously so the outer fast-path check below
        # doesn't accidentally block the restart when called from closedPrefsConfigUi.
        if self._web_poll_task and not self._web_poll_task.done() and loop:
            loop.call_soon_threadsafe(self._web_poll_task.cancel)
            self._web_poll_task = None
        if not self.pluginPrefs.get("useWebData", False):
            return
        api_token = self.pluginPrefs.get("apiToken", "").strip()
        if not api_token:
            self.logger.warning("WeatherFlow web API: enabled but no token configured")
            return
        if not loop or not loop.is_running():
            return
        def _schedule():
            # Inner guard: call_soon_threadsafe queues work without waiting, so two
            # rapid callers can both pass the outer None-check before either _schedule
            # runs. The event loop executes _schedule calls serially, so this check
            # is race-safe.
            if self._web_poll_task and not self._web_poll_task.done():
                return
            self._web_poll_task = loop.create_task(self._web_poll_loop())
            self.logger.info("WeatherFlow web API poller started")
        loop.call_soon_threadsafe(_schedule)

    async def _web_poll_loop(self) -> None:
        """Async loop: poll the WeatherFlow REST API.

        Interval is adaptive: 60 s when any device is in web-only mode (temperature
        and all sensor states come from web), 300 s when UDP is active (web only
        supplements rain totals and conditions — all slow-changing data).

        The 60-second startup delay lets the UDP listener complete its first device
        discovery cycle so the initial web poll doesn't overwrite freshly arrived
        UDP data with stale web values.
        """
        await asyncio.sleep(60)
        while True:
            if not self.pluginPrefs.get("useWebData", False):
                return
            api_token = self.pluginPrefs.get("apiToken", "").strip()
            if not api_token:
                return
            try:
                has_web_only = await self._web_poll_all(api_token)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("WeatherFlow web API: unexpected error in poll cycle")
                has_web_only = False
            interval = 60 if has_web_only else 300
            await asyncio.sleep(interval)

    async def _web_poll_all(self, api_token: str) -> bool:
        """Fetch and apply web obs for every tracked ST- device.

        Returns True if any device was in web-only mode (no active UDP), which
        signals the caller to use a shorter poll interval.

        Failure tracking: after 3 consecutive failures for a station, polling is
        suspended and a single warning is logged. Fix the station ID or save the
        device config to reset the counter.
        """
        _SUSPEND_AFTER = 3
        has_web_only = False

        # --- Web-only devices: iterate Indigo devices directly, no SN needed ---
        for dev in indigo.devices.iter("self"):
            if not dev.pluginProps.get("webOnly", False):
                continue
            has_web_only = True
            station_id_str = dev.pluginProps.get("stationId", "").strip()
            if not station_id_str or not station_id_str.isdigit():
                continue
            station_id = int(station_id_str)
            fail_count = self._station_fail_count.get(station_id, 0)
            if fail_count >= _SUSPEND_AFTER:
                continue
            try:
                obs, err = await self._fetch_station_obs(station_id, api_token)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception(
                    "WeatherFlow web API: unexpected error polling %s (station %d)",
                    dev.name, station_id,
                )
                continue
            if obs is not None:
                if fail_count:
                    self._station_fail_count[station_id] = 0
                self._on_web_obs(dev.id, obs)
            else:
                new_count = fail_count + 1
                self._station_fail_count[station_id] = new_count
                if new_count < _SUSPEND_AFTER:
                    self.logger.warning(
                        "%s: web API error for station %d — %s", dev.name, station_id, err
                    )
                else:
                    self.logger.warning(
                        "%s: web API station %d suspended after %d consecutive failures (%s). "
                        "Edit the device to correct the station ID and resume polling.",
                        dev.name, station_id, _SUSPEND_AFTER, err,
                    )

        # --- Non-web-only ST- devices: supplement UDP with web data ---
        sn_list = [sn for sn in self._serial_to_dev_id if sn.startswith("ST")]
        if not sn_list:
            return has_web_only

        missing = [sn for sn in sn_list if sn not in self._station_id_map]
        if missing:
            await self._discover_stations(api_token)

        for sn in sn_list:
            station_id = self._station_id_map.get(sn)
            if station_id is None:
                self.logger.debug("%s: station_id not found — check token and account", sn)
                continue
            fail_count = self._station_fail_count.get(station_id, 0)
            if fail_count >= _SUSPEND_AFTER:
                continue
            try:
                obs, err = await self._fetch_station_obs(station_id, api_token)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("WeatherFlow web API: unexpected error polling %s", sn)
                continue
            if obs is not None:
                if fail_count:
                    self._station_fail_count[station_id] = 0
                dev_id = self._serial_to_dev_id.get(sn)
                if dev_id is not None:
                    self._on_web_obs(dev_id, obs)
            else:
                new_count = fail_count + 1
                self._station_fail_count[station_id] = new_count
                if new_count < _SUSPEND_AFTER:
                    self.logger.warning(
                        "%s: web API error for station %d — %s", sn, station_id, err
                    )
                else:
                    self.logger.warning(
                        "%s: web API station %d suspended after %d consecutive failures (%s). "
                        "Edit the device to correct the station ID and resume polling.",
                        sn, station_id, _SUSPEND_AFTER, err,
                    )

        return has_web_only

    async def _discover_stations(self, api_token: str) -> None:
        """Map ST- serial numbers to WeatherFlow station IDs via the REST API."""
        data, err = await self._fetch_json(f"{_WEB_API_BASE}/stations?token={api_token}")
        if data is None:
            if err:
                self.logger.warning("WeatherFlow web API: could not fetch station list — %s", err)
            return
        for station in data.get("stations", []):
            station_id = station.get("station_id")
            if station_id is None:
                continue
            for dev in station.get("devices", []):
                sn = dev.get("serial_number", "")
                if sn in self._serial_to_dev_id and sn not in self._station_id_map:
                    self._station_id_map[sn] = int(station_id)
                    self.logger.info("%s: mapped to station_id=%d via web API", sn, station_id)

    async def _fetch_station_obs(self, station_id: int, api_token: str) -> tuple[dict | None, str | None]:
        """Fetch current_conditions from the WeatherFlow better_forecast endpoint.

        Also fetches /observations/stn/{id}?api_key=&bucket=1 to check device status.
        better_forecast.station.is_station_online is always True even with a flat
        battery — it cannot be used for offline detection.  /observations/stn returns
        obs:[] when the device has no recent observations, which is the definitive
        offline signal.  bucket=1 requests the latest 1-minute record only.
        The /diagnostics endpoint has richer data but requires a partner API key.

        Injects into the returned current_conditions dict:
            _obs_timestamp    — timestamp from obs[0] when station is online
            _station_offline  — True when obs list is empty (device offline)
            _station_status_message — status_message from the obs response

        If the /observations/stn call fails (network error) neither key is injected
        and the update proceeds — transient errors should not block updates.

        Returns (augmented current_conditions dict, error_message).
        error_message is None on success.
        """
        url = (
            f"{_WEB_API_BASE}/better_forecast"
            f"?station_id={station_id}&token={api_token}"
            "&units_temp=c&units_wind=mps&units_pressure=mb&units_precip=mm&units_distance=km"
        )
        data, err = await self._fetch_json(url)
        if data is None:
            return None, err

        cc = data.get("current_conditions") or {}

        # --- Check /observations/stn to detect whether the device is online ---
        # Uses the documented personal station observations endpoint with the user's
        # own api_key token. bucket=1 returns just the latest observation record.
        # When the station is offline, obs:[] is returned — the definitive offline
        # signal. better_forecast.station.is_station_online cannot be used (always
        # True even with flat battery). /diagnostics requires a partner key.
        #
        # If this call fails (network error), leave markers absent and fall through —
        # transient errors should not block all web updates.
        obs_url = (
            f"{_WEB_API_BASE}/observations/stn/{station_id}"
            f"?api_key={api_token}&bucket=1"
        )
        obs_data, obs_err = await self._fetch_json(obs_url)
        if obs_data is not None:
            obs_list = obs_data.get("obs", [])
            ob_fields = obs_data.get("ob_fields", [])
            status = obs_data.get("status", {})
            self.logger.debug(
                "station %d: /observations/stn status=%s  obs count=%d",
                station_id, status, len(obs_list),
            )
            if not obs_list:
                # Station is offline — no observations returned
                cc["_station_offline"] = True
                cc["_station_status_message"] = status.get("status_message", "")
            else:
                # obs is a positional array; ob_fields names the columns.
                # "timestamp" is always the first field but look it up to be safe.
                # Use obs[-1] (last/most recent record) in case bucket=1 returns
                # multiple records for the current day.
                ts_idx = ob_fields.index("timestamp") if "timestamp" in ob_fields else 0
                latest = obs_list[-1]
                if latest and len(latest) > ts_idx:
                    real_ts = latest[ts_idx]
                    if real_ts is not None:
                        cc["_obs_timestamp"] = int(real_ts)
                        self.logger.debug(
                            "station %d: obs[%d] timestamp=%d (age %.0f s)",
                            station_id, len(obs_list) - 1, real_ts, time.time() - int(real_ts),
                        )
        else:
            self.logger.debug(
                "station %d: could not fetch /observations/stn — %s", station_id, obs_err
            )

        return cc, None

    async def _fetch_json(self, url: str) -> tuple[dict | None, str | None]:
        """Fetch a JSON endpoint in a thread pool.

        Returns (data, error_message). error_message is None on success so the
        caller can decide how to log failures (e.g. suppress after repeated errors).
        """
        loop = asyncio.get_running_loop()
        try:
            def _do_fetch():
                req = urllib.request.Request(
                    url, headers={"User-Agent": "WeatherFlow-Indigo/2.0"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            return await loop.run_in_executor(None, _do_fetch), None
        except Exception as ex:
            return None, str(ex)

    # -------------------------------------------------------------------------
    # Public station poller (no personal token — uses system-wide public API key)
    # -------------------------------------------------------------------------

    def _start_public_poller(self) -> None:
        """Start the public station poll task if not already running.

        The guard is checked both here (fast path) and inside _schedule (race-safe).
        call_soon_threadsafe queues work on the event loop without waiting, so two
        callers can both pass the outer check before either _schedule runs. The inner
        check is always on the event loop thread, so it is strictly serial and safe.
        """
        loop = self._event_loop
        if not loop or not loop.is_running():
            return
        if self._public_poll_task and not self._public_poll_task.done():
            return  # fast path: clearly already running
        def _schedule():
            # Inner guard: catches the race where startup() and deviceStartComm()
            # both pass the outer check before either _schedule executes.
            if self._public_poll_task and not self._public_poll_task.done():
                return
            self._public_poll_task = loop.create_task(self._public_poll_loop())
            self.logger.info("WeatherFlow public station poller started")
        loop.call_soon_threadsafe(_schedule)

    async def _public_poll_loop(self) -> None:
        """Poll all publicTempestStation devices every 120 seconds."""
        await asyncio.sleep(15)  # brief startup delay
        while True:
            try:
                await self._public_poll_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("WeatherFlow public station poller: unexpected error")
            await asyncio.sleep(120)

    async def _public_poll_all(self) -> None:
        _SUSPEND_AFTER = 3
        for dev in indigo.devices.iter("self"):
            if dev.deviceTypeId != "publicTempestStation":
                continue
            station_id_str = dev.pluginProps.get("stationId", "").strip()
            if not station_id_str or not station_id_str.isdigit():
                continue
            station_id = int(station_id_str)
            fail_count = self._public_fail_count.get(station_id, 0)
            if fail_count >= _SUSPEND_AFTER:
                continue
            unit_prefs = _get_unit_prefs(dev)
            unit_prefs["distUnit"] = dev.pluginProps.get("distUnit", "km")
            try:
                data, err = await self._fetch_public_station_obs(station_id, unit_prefs)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("Public station %d: unexpected error", station_id)
                continue
            if data is not None:
                if fail_count:
                    self._public_fail_count[station_id] = 0
                self._on_public_obs(dev.id, data, unit_prefs)
            else:
                new_count = fail_count + 1
                self._public_fail_count[station_id] = new_count
                if new_count < _SUSPEND_AFTER:
                    self.logger.warning(
                        "%s: public station %d poll error — %s", dev.name, station_id, err
                    )
                else:
                    self.logger.warning(
                        "%s: public station %d suspended after %d consecutive failures (%s). "
                        "Edit the device to reset.",
                        dev.name, station_id, _SUSPEND_AFTER, err,
                    )

    async def _fetch_public_station_obs(
        self, station_id: int, unit_prefs: dict
    ) -> tuple[dict | None, str | None]:
        """Fetch observations for a public station using the system API key."""
        temp_p  = _UNIT_PREFS_TO_API_TEMP.get(unit_prefs.get("temp", "celsius"), "c")
        wind_p  = _UNIT_PREFS_TO_API_WIND.get(unit_prefs.get("wind", "ms"), "ms")
        press_p = _UNIT_PREFS_TO_API_PRESSURE.get(unit_prefs.get("pressure", "hpa"), "hpa")
        rain_p  = _UNIT_PREFS_TO_API_RAIN.get(unit_prefs.get("rain", "mm"), "mm")
        url = (
            f"{_WEB_API_BASE}/observations/station/{station_id}"
            f"?api_key={_PUBLIC_API_KEY}"
            f"&units_temp={temp_p}&units_wind={wind_p}"
            f"&units_pressure={press_p}&units_precip={rain_p}&units_distance=km"
        )
        loop = asyncio.get_running_loop()
        try:
            def _do_fetch():
                req = urllib.request.Request(url, headers=_PUBLIC_HEADERS)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            data = await loop.run_in_executor(None, _do_fetch)
        except Exception as ex:
            return None, str(ex)
        status = data.get("status", {})
        if status.get("status_code", -1) != 0:
            return None, status.get("status_message", "unknown API error")
        return data, None

    def _on_public_obs(self, dev_id: int, data: dict, unit_prefs: dict) -> None:
        dev = indigo.devices.get(dev_id)
        if dev is None:
            return

        # Age-gate: public endpoint returns obs[0]["timestamp"] (Unix epoch).
        # Reject observations older than 10 minutes — stale cached values are
        # worse than leaving the last-good data in place.
        _MAX_OBS_AGE_SECS = 600
        obs_list = data.get("obs", [])
        obs_ts = obs_list[0].get("timestamp") if obs_list else None
        if obs_ts is not None:
            try:
                obs_age_secs = time.time() - int(obs_ts)
                self.logger.debug(
                    "%s: public observation age %.0f s (%.1f min)",
                    dev.name, obs_age_secs, obs_age_secs / 60,
                )
                if obs_age_secs > _MAX_OBS_AGE_SECS:
                    self.logger.warning(
                        "%s: public observation is %.0f min old (timestamp=%s) — skipping update",
                        dev.name, obs_age_secs / 60, obs_ts,
                    )
                    return
            except (TypeError, ValueError):
                pass

        try:
            ll = indigo.server.getLatitudeAndLongitude()
            indigo_lat: float | None = float(ll[0]) if ll[0] is not None else None
            indigo_lon: float | None = float(ll[1]) if ll[1] is not None else None
        except Exception:
            indigo_lat, indigo_lon = None, None
        states = _build_public_obs_states(data, unit_prefs, indigo_lat, indigo_lon)
        if not states:
            return
        self.logger.debug("%s: public obs — %d states updated", dev.name, len(states))
        self._safe_update_states(dev, states)

    def _on_web_obs(self, dev_id: int, obs: dict) -> None:
        """Apply a web API current_conditions dict to the matching Indigo device.

        include_standard is True only when no local UDP data is flowing (web-only mode).
        With active UDP, web updates only states UDP doesn't provide: rain totals
        (authoritative, rain-check corrected), rain duration, conditions, icon, and
        hourly lightning counts. All real-time sensor readings (temp, pressure, wind,
        UV, etc.) are left to the faster UDP path.
        """
        dev = indigo.devices.get(dev_id)
        if dev is None:
            return
        unit_prefs = _get_unit_prefs(dev)

        # --- Staleness / offline gate ---
        # /observations/stn returns obs:[] when the device is offline. better_forecast
        # keeps serving stale cached data indefinitely and reports is_station_online=True
        # even with a flat battery — it cannot be used for offline detection.
        #
        # Two thresholds:
        #   > 10 minutes stale  → reject update, mark deviceStatus = "Stale data"
        #   > 30 minutes stale  → reject update, mark deviceStatus = "Offline"
        #
        # Staleness duration is tracked by _web_stale_since[dev_id], set on first
        # detection and cleared when a good update succeeds.
        _STALE_SECS   = 600   # 10 minutes
        _OFFLINE_SECS = 1800  # 30 minutes

        now = time.time()
        data_age: float | None = None   # seconds since last good observation

        if obs.get("_station_offline"):
            # No observations at all — station is confirmed offline.
            # We don't have a real observation timestamp so use _web_stale_since to
            # measure how long we have been in this state.
            status_msg = obs.get("_station_status_message", "")
            if dev_id not in self._web_stale_since:
                self._web_stale_since[dev_id] = now
            data_age = now - self._web_stale_since[dev_id]
            self.logger.warning(
                "%s: station offline — no recent observations%s (stale %.0f min)",
                dev.name,
                f" ({status_msg})" if status_msg else "",
                data_age / 60,
            )
        else:
            real_ts = obs.get("_obs_timestamp")
            if real_ts is not None:
                try:
                    data_age = now - int(real_ts)
                    self.logger.debug(
                        "%s: web observation age %.0f s (%.1f min)",
                        dev.name, data_age, data_age / 60,
                    )
                    if data_age > _STALE_SECS:
                        if dev_id not in self._web_stale_since:
                            self._web_stale_since[dev_id] = now - data_age
                        self.logger.warning(
                            "%s: web observation is %.0f min old (obs_timestamp=%s)",
                            dev.name, data_age / 60, real_ts,
                        )
                except (TypeError, ValueError):
                    data_age = None

        if data_age is not None and data_age > _STALE_SECS:
            # Determine severity based on total stale duration
            stale_duration = now - self._web_stale_since.get(dev_id, now - data_age)
            if stale_duration >= _OFFLINE_SECS:
                error_msg = "Offline"
            else:
                error_msg = "Stale data"
            # Update deviceStatus string and set Indigo device error state (turns red in UI)
            dev.updateStatesOnServer([{"key": "deviceStatus", "value": error_msg}])
            dev.setErrorStateOnServer(error_msg)
            return

        # Data is fresh — clear stale tracker and any Indigo error state.
        # On recovery, force include_standard=True so all states are pushed
        # immediately rather than waiting for the next UDP observation cycle.
        # State-list reconciliation is handled lazily by _safe_update_states:
        # it calls stateListOrDisplayStateIdChanged() only when a specific key
        # is found to be missing, avoiding spurious "not defined" errors that
        # appeared when the whole list was synced up-front.
        recovering = dev_id in self._web_stale_since
        self._web_stale_since.pop(dev_id, None)
        if recovering:
            self.logger.info("%s: station recovered — resuming state updates", dev.name)
        dev.setErrorStateOnServer(None)

        # Respect the explicit web-only flag first — it overrides everything.
        # A device marked web-only always gets full state from the web API,
        # regardless of whether UDP happens to be active on the same network.
        # For non-web-only devices, fall back to checking live UDP activity.
        # On recovery from offline/stale, force include_standard so all states
        # are pushed immediately without waiting for the next UDP observation.
        if recovering or dev.pluginProps.get("webOnly", False):
            include_standard = True
        else:
            sn = dev.pluginProps.get("serialNumber", "")
            wf_dev = self._discovered.get(sn)
            udp_active = False
            if wf_dev is not None:
                last = getattr(wf_dev, "_last_report", None)
                udp_active = last is not None and (time.time() - last) < 300
            include_standard = not udp_active

        states = _build_web_observation_states(obs, unit_prefs, include_standard=include_standard)
        if not states:
            return

        if self.logger.isEnabledFor(logging.DEBUG):
            label = dev.name
            mode = "web-only (no UDP)" if include_standard else "web supplement (UDP active)"
            self.logger.debug("%s: web obs — mode=%s, %d states:", label, mode, len(states))
            for s in states:
                key = s["key"]
                current = dev.states.get(key, "<not set>")
                new_val = s.get("uiValue", s.get("value"))
                self.logger.debug("%s:   %-38s %r → %r", label, key, current, new_val)

        self._safe_update_states(dev, states)


# =============================================================================
# Public station helpers
# =============================================================================

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in km between two lat/lon points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return initial bearing (0–360°) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _distance_description(dist_km: float, bearing_deg: float, use_miles: bool = False) -> str:
    """Return a human-readable distance string like '1.5 km North' or '600 m NE'."""
    cardinal = _degrees_to_cardinal(bearing_deg)
    if use_miles:
        dist_mi = dist_km * 0.621371
        if dist_mi < 0.1:
            return f"{int(dist_mi * 5280)} ft {cardinal}"
        return f"{dist_mi:.1f} mi {cardinal}"
    if dist_km < 1.0:
        return f"{int(round(dist_km * 1000))} m {cardinal}"
    return f"{dist_km:.1f} km {cardinal}"


def _pub_state(
    states: list[dict], key: str, value: object, dp: int, sym: str = ""
) -> None:
    """Append a pre-converted state (value already in user's units)."""
    if value is None:
        return
    try:
        v = round(float(value), dp)  # type: ignore[arg-type]
        entry: dict = {"key": key, "value": v, "decimalPlaces": dp}
        if sym:
            entry["uiValue"] = f"{v} {sym}"
        states.append(entry)
    except (TypeError, ValueError):
        pass


def _build_public_obs_states(
    data: dict,
    unit_prefs: dict,
    indigo_lat: float | None,
    indigo_lon: float | None,
) -> list[dict]:
    """Build Indigo state list from a WeatherFlow public observations/station response.

    Values are already in the user's requested units (passed as API query params),
    so no Pint conversion is needed — just format and label.
    """
    states: list[dict] = []
    obs_list = data.get("obs", [])
    obs: dict = obs_list[0] if obs_list else {}

    # --- Station identity ---
    states.append({"key": "station_name", "value": str(data.get("station_name", ""))})
    lat = data.get("latitude")
    lon = data.get("longitude")
    elev = data.get("elevation")
    if lat is not None:
        states.append({"key": "latitude",  "value": round(float(lat), 6)})
    if lon is not None:
        states.append({"key": "longitude", "value": round(float(lon), 6)})
    if elev is not None:
        _pub_state(states, "elevation", float(elev), 1, "m")

    # --- Distance from Indigo server ---
    if lat is not None and lon is not None and indigo_lat is not None and indigo_lon is not None:
        slat, slon = float(lat), float(lon)
        dist_km = _haversine(indigo_lat, indigo_lon, slat, slon)
        brg = _bearing_deg(indigo_lat, indigo_lon, slat, slon)
        cardinal = _degrees_to_cardinal(brg)
        dist_mi = dist_km * 0.621371
        use_miles = unit_prefs.get("distUnit", "km") == "mi"
        desc = _distance_description(dist_km, brg, use_miles)
        states.append({"key": "distance_km",
                        "value": round(dist_km, 2), "decimalPlaces": 2,
                        "uiValue": f"{dist_km:.2f} km"})
        states.append({"key": "distance_mi",
                        "value": round(dist_mi, 2), "decimalPlaces": 2,
                        "uiValue": f"{dist_mi:.2f} mi"})
        states.append({"key": "bearing",
                        "value": round(brg, 1), "decimalPlaces": 1,
                        "uiValue": f"{brg:.1f}°"})
        states.append({"key": "bearing_cardinal",     "value": cardinal})
        states.append({"key": "distance_description", "value": desc})

    # --- Unit display symbols ---
    t_sym  = _UNIT_DISPLAY.get(unit_prefs.get("temp",     "celsius"), "°C")
    p_sym  = _UNIT_DISPLAY.get(unit_prefs.get("pressure", "hpa"),     "hPa")
    p_dp   = 2 if unit_prefs.get("pressure") == "inhg" else 1
    w_sym  = _UNIT_DISPLAY.get(unit_prefs.get("wind",     "ms"),      "m/s")
    r_sym  = _UNIT_DISPLAY.get(unit_prefs.get("rain",     "mm"),      "mm")
    r_dp   = 3 if unit_prefs.get("rain") == "inch" else 2

    # --- Temperature ---
    _pub_state(states, "air_temperature",        obs.get("air_temperature"),      1, t_sym)
    _pub_state(states, "dew_point_temperature",  obs.get("dew_point"),            1, t_sym)
    _pub_state(states, "wet_bulb_temperature",   obs.get("wet_bulb_temperature"), 1, t_sym)
    _pub_state(states, "feels_like_temperature", obs.get("feels_like"),           1, t_sym)
    _pub_state(states, "heat_index",             obs.get("heat_index"),           1, t_sym)
    _pub_state(states, "wind_chill_temperature", obs.get("wind_chill"),           1, t_sym)
    _dt_sym = "Δ°F" if unit_prefs.get("temp") == "fahrenheit" else "Δ°C"
    _pub_state(states, "delta_t",                obs.get("delta_t"),              1, _dt_sym)
    _pub_state(states, "air_density",            obs.get("air_density"),          3, "kg/m³")

    # --- Atmospheric ---
    rh = obs.get("relative_humidity")
    if rh is not None:
        rh_i = int(round(float(rh)))
        states.append({"key": "relative_humidity", "value": rh_i, "uiValue": f"{rh_i} %"})
    _pub_state(states, "station_pressure",   obs.get("station_pressure"),   p_dp, p_sym)
    _pub_state(states, "sea_level_pressure", obs.get("sea_level_pressure"), p_dp, p_sym)
    pt = obs.get("pressure_trend")
    if pt is not None:
        states.append({"key": "pressure_trend", "value": str(pt)})

    # --- Light / UV ---
    solar = obs.get("solar_radiation")
    if solar is not None:
        solar_i = int(round(float(solar)))
        states.append({"key": "solar_radiation", "value": solar_i, "uiValue": f"{solar_i} W/m²"})
    brt = obs.get("brightness")
    if brt is not None:
        brt_i = int(round(float(brt)))
        states.append({"key": "illuminance", "value": brt_i, "uiValue": f"{brt_i} lx"})
    _pub_state(states, "uv", obs.get("uv"), 1, "UV")

    # --- Wind ---
    _pub_state(states, "wind_average", obs.get("wind_avg"),  1, w_sym)
    _pub_state(states, "wind_speed",   obs.get("wind_avg"),  1, w_sym)
    _pub_state(states, "wind_gust",    obs.get("wind_gust"), 1, w_sym)
    _pub_state(states, "wind_lull",    obs.get("wind_lull"), 1, w_sym)
    wd = obs.get("wind_direction")
    if wd is not None:
        wd_f = float(wd)
        states.append({"key": "wind_direction",
                        "value": round(wd_f, 1), "decimalPlaces": 1, "uiValue": f"{wd_f:.1f}°"})
        states.append({"key": "wind_direction_average",
                        "value": round(wd_f, 1), "decimalPlaces": 1, "uiValue": f"{wd_f:.1f}°"})
        card = _degrees_to_cardinal(wd_f)
        states.append({"key": "wind_direction_cardinal",         "value": card})
        states.append({"key": "wind_direction_average_cardinal", "value": card})

    # --- Rain ---
    _pub_state(states, "rain_today",     obs.get("precip_accum_local_day"),       r_dp, r_sym)
    _pub_state(states, "rain_yesterday", obs.get("precip_accum_local_yesterday"), r_dp, r_sym)
    _pub_state(states, "rain_last_1hr",  obs.get("precip_accum_last_1hr"),        r_dp, r_sym)
    rd_today = obs.get("precip_minutes_local_day")
    if rd_today is not None:
        states.append({"key": "rain_duration_today",     "value": int(rd_today)})
    rd_yesterday = obs.get("precip_minutes_local_yesterday")
    if rd_yesterday is not None:
        states.append({"key": "rain_duration_yesterday", "value": int(rd_yesterday)})

    # --- Lightning ---
    lc = obs.get("lightning_strike_count")
    if lc is not None:
        states.append({"key": "lightning_strike_count", "value": int(lc)})
    lc1 = obs.get("lightning_strike_count_last_1hr")
    if lc1 is not None:
        states.append({"key": "lightning_count_last_1hr", "value": int(lc1)})
    lc3 = obs.get("lightning_strike_count_last_3hr")
    if lc3 is not None:
        states.append({"key": "lightning_count_last_3hr", "value": int(lc3)})
    _pub_state(states, "last_strike_distance", obs.get("lightning_strike_last_distance"), 1, "km")

    # --- Timestamp ---
    ts = obs.get("timestamp")
    if ts is not None:
        try:
            dt_str = datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
            states.append({"key": "last_updated", "value": dt_str})
        except Exception:
            pass

    # --- Unit indicators ---
    states.extend(_build_unit_states(unit_prefs))
    states.append({"key": "deviceStatus", "value": "Active"})
    return states


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

    # Temperature differential (delta_t) — ×1.8 to convert Δ°C→Δ°F; no +32 offset
    ("delta_t", "celsius"):    ("Δ°C", 1, None, None),
    ("delta_t", "fahrenheit"): ("Δ°F", 1, None, 1.8),

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
    "count":      ("",      0),
    "seconds":    ("s",     0),
    "minutes":    ("min",   0),
}

_DEFAULT_UNIT_IDS: dict[str, str] = {
    "temp":      "celsius",
    "delta_t":   "celsius",
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
    temp_unit = props.get("tempUnit", "fahrenheit" if legacy_imperial else "celsius")
    return {
        "temp":      temp_unit,
        "delta_t":   temp_unit,   # differential — same C/F preference as absolute temp
        "pressure":  props.get("pressureUnit", "inhg" if legacy_imperial else "hpa"),
        "wind":      props.get("windUnit",     "mph"  if legacy_imperial else "ms"),
        "rain":      rain_unit,
        "rain_rate": rain_unit,
        "alt":       props.get("altUnit",      "ft"   if legacy_imperial else "m"),
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

def _rain_intensity(rate_mm_h: float | None) -> str:
    """Return a human-readable rain intensity label from a rate in mm/h."""
    if rate_mm_h is None:
        return "None"
    if rate_mm_h <= 0:
        return "None"
    if rate_mm_h < 0.5:
        return "Very Light"
    if rate_mm_h < 2.5:
        return "Light"
    if rate_mm_h < 10.0:
        return "Moderate"
    if rate_mm_h < 50.0:
        return "Heavy"
    return "Violent"


def _build_observation_states(
    device: WeatherFlowSensorDevice,
    altitude_qty: Any = None,
    unit_prefs: dict | None = None,
    rain_today_mm: float | None = None,
    rain_yesterday_mm: float | None = None,
    rain_source: str = "",
) -> list[dict]:
    if unit_prefs is None:
        unit_prefs = {}
    states: list[dict] = []

    # --- Temperature ---
    _add_u(states, "air_temperature",        getattr(device, "air_temperature", None),       "temp",    unit_prefs)
    _add_u(states, "temperature",            getattr(device, "air_temperature", None),       "temp",    unit_prefs)
    _add_u(states, "dew_point_temperature",  getattr(device, "dew_point_temperature", None), "temp",    unit_prefs)
    _add_u(states, "wet_bulb_temperature",   getattr(device, "wet_bulb_temperature", None),  "temp",    unit_prefs)
    _hi = getattr(device, "heat_index", None)
    if _hi is not None:
        _add_u(states, "heat_index", _hi, "temp", unit_prefs)
    else:
        # heat_index conditions not met (temp < 80 °F or rh < 40 %) — write None so
        # the state is always updated and stale readings never persist.
        states.append({"key": "heat_index", "value": None, "uiValue": ""})
    _add_u(states, "delta_t",               getattr(device, "delta_t", None),               "delta_t", unit_prefs)

    if isinstance(device, TempestDevice):
        _add_u(states, "feels_like_temperature", device.feels_like_temperature, "temp", unit_prefs)
        _wc = device.wind_chill_temperature
        if _wc is not None:
            _add_u(states, "wind_chill_temperature", _wc, "temp", unit_prefs)
        else:
            # Wind chill conditions not met (temp > 50 °F or wind < 3 mph) — write None so
            # the state is always updated and stale readings never persist.
            states.append({"key": "wind_chill_temperature", "value": None, "uiValue": ""})

    # --- Atmospheric ---
    _add_u(states, "relative_humidity", getattr(device, "relative_humidity", None), "percent",  unit_prefs)
    _add_u(states, "station_pressure",  getattr(device, "station_pressure", None),  "pressure", unit_prefs)
    _add_u(states, "vapor_pressure",    getattr(device, "vapor_pressure", None),    "pressure", unit_prefs)
    _add_u(states, "air_density",       getattr(device, "air_density", None),       "density",  unit_prefs)

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
    _add_u(states, "illuminance",     getattr(device, "illuminance", None),     "lux",        unit_prefs)
    _add_u(states, "solar_radiation", getattr(device, "solar_radiation", None), "irradiance", unit_prefs)
    _add_u(states, "uv",              getattr(device, "uv", None),              "uv",         unit_prefs)

    # --- Rain (SkySensorType only: Sky and Tempest have rain sensors; Air does not) ---
    if isinstance(device, SkySensorType):
        _add_u(states, "rain_accumulation_previous_minute",
               getattr(device, "rain_accumulation_previous_minute", None), "rain", unit_prefs)
        _add_u(states, "rain_rate", getattr(device, "rain_rate", None), "rain_rate", unit_prefs)

        # Rain intensity label derived from rain_rate (always in mm/h from the library)
        rate_raw = getattr(device, "rain_rate", None)
        rate_mm_h = float(rate_raw.magnitude) if rate_raw is not None and hasattr(rate_raw, "magnitude") else (float(rate_raw) if rate_raw is not None else None)
        states.append({"key": "rain_intensity", "value": _rain_intensity(rate_mm_h)})

        # Local rain totals — UDP path only.  The web API never writes these states.
        # rain_today_local / rain_today_local_raw_mm are the raw device values (not
        # rain-check corrected).  rain_today_local_raw_mm is also the accumulation
        # baseline for fallback mode and the midnight-rollover capture source.
        # rain_today / rain_today_raw_mm / rain_yesterday are written exclusively by
        # the web API path so they always show the rain-check corrected totals.
        if rain_today_mm is not None:
            _add_u(states, "rain_today_local", rain_today_mm * _UNIT_MM, "rain", unit_prefs)
            states.append({"key": "rain_today_local_raw_mm", "value": round(rain_today_mm, 3)})

        # Track the date so midnight rollover detection survives restarts
        states.append({"key": "rain_today_date", "value": datetime.date.today().isoformat()})

        # Local source indicator: "hub" (index 18, authoritative) or
        # "accumulated" (per-minute fallback when hub omits index 18, e.g. power-save mode).
        # Web never writes this state — it only reflects the local device path.
        if rain_source:
            states.append({"key": "rain_today_source", "value": rain_source})

        # Local yesterday (captured from rain_today_local_raw_mm at midnight rollover).
        # rain_yesterday is written exclusively by the web API.
        if rain_yesterday_mm is not None:
            _add_u(states, "rain_yesterday_local", rain_yesterday_mm * _UNIT_MM, "rain", unit_prefs)

        _precip_type = getattr(device, "precipitation_type", None)
        if _precip_type is not None:
            states.append({"key": "precipitation_type", "value": _precip_type.name.lower()})

    # --- Lightning ---
    _strike_count = getattr(device, "lightning_strike_count", None)
    if _strike_count is not None:
        states.append({"key": "lightning_strike_count", "value": _strike_count})
    _add_u(states, "lightning_strike_average_distance",
           getattr(device, "lightning_strike_average_distance", None), "distance", unit_prefs)

    # --- Wind ---
    states.extend(_build_wind_states(device, unit_prefs))
    _add_u(states, "wind_sample_interval", getattr(device, "wind_sample_interval", None), "seconds", unit_prefs)

    # --- Reporting ---
    _add_u(states, "report_interval", getattr(device, "report_interval", None), "minutes", unit_prefs)

    # --- Rain Check (WeatherFlow's precipitation analysis / verification status) ---
    rain_check = getattr(device, "rain_check", None)
    if rain_check is not None:
        states.append({"key": "rain_check", "value": rain_check})

    # --- Battery ---
    _add_u(states, "battery",         device.battery,         "volts",   unit_prefs)
    _add_u(states, "battery_percent", device.battery_percent, "percent", unit_prefs)

    # --- Timestamps / diagnostics ---
    if device.last_report:
        states.append({"key": "last_report", "value": str(device.last_report)})

    _psm = getattr(device, "power_save_mode", None)
    if _psm is not None:
        states.append({"key": "power_save_mode", "value": _psm.name})

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
    _add_u(states, "wind_speed",             getattr(device, "wind_speed", None),             "wind",    unit_prefs)
    _add_u(states, "wind_average",           getattr(device, "wind_average", None),           "wind",    unit_prefs)
    _add_u(states, "wind_gust",              getattr(device, "wind_gust", None),              "wind",    unit_prefs)
    _add_u(states, "wind_lull",              getattr(device, "wind_lull", None),              "wind",    unit_prefs)
    _add_u(states, "wind_direction",         getattr(device, "wind_direction", None),         "degrees", unit_prefs)
    _add_u(states, "wind_direction_average", getattr(device, "wind_direction_average", None), "degrees", unit_prefs)
    cardinal = getattr(device, "wind_direction_cardinal", None)
    if cardinal:
        states.append({"key": "wind_direction_cardinal", "value": cardinal})
    avg_cardinal = getattr(device, "wind_direction_average_cardinal", None)
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
    _PRIMARY_SENSOR_MASK = 0x1FF  # bits 0-8: the 9 documented sensor failure flags
    sensor_status_raw = getattr(device, "_sensor_status", 0) or 0
    if (sensor_status_raw & _PRIMARY_SENSOR_MASK) == _PRIMARY_SENSOR_MASK:
        # All 9 primary bits set simultaneously is a firmware artifact (seen in
        # firmware 181) where the hardware register is read before sensor self-test
        # completes. The WeatherFlow app shows OK in this case; we match that.
        states.append({"key": "sensor_status", "value": "OK"})
    else:
        ss = device.sensor_status
        if ss is not None:
            states.append({"key": "sensor_status", "value": ", ".join(ss) if ss else "OK"})
    return states


def _add_int(states: list[dict], key: str, value: Any) -> None:
    if value is None:
        return
    try:
        mag = value.magnitude if hasattr(value, "magnitude") else value
        states.append({"key": key, "value": int(mag)})
    except (TypeError, AttributeError, ValueError):
        pass


def _build_web_observation_states(
    obs: dict,
    unit_prefs: dict,
    include_standard: bool = False,
) -> list[dict]:
    """Build Indigo state list from a WeatherFlow better_forecast current_conditions dict.

    When include_standard is False (local UDP device is active), only web-exclusive states
    are written so UDP data is not overwritten. When True (web-only mode), all sensor states
    are populated from the web response.
    """
    states: list[dict] = []

    def _qty(key: str, pint_unit: str):
        v = obs.get(key)
        if v is None:
            return None
        try:
            return units.Quantity(float(v), pint_unit)
        except Exception:
            return None

    # --- Authoritative rain totals (always update — web data is rain-check corrected) ---
    # Web writes rain_today / rain_today_raw_mm / rain_yesterday (display / best values).
    # rain_today / rain_today_raw_mm / rain_yesterday are written ONLY here (web path).
    # They always contain rain-check corrected totals from the WeatherFlow API.
    # The web path deliberately does NOT write:
    #   rain_today_local / rain_today_local_raw_mm / rain_yesterday_local / rain_today_source
    # Those are owned exclusively by the UDP path.
    rain_today = obs.get("precip_accum_local_day")
    if rain_today is not None:
        rain_today_mm = float(rain_today)
        _add_u(states, "rain_today", rain_today_mm * _UNIT_MM, "rain", unit_prefs)
        states.append({"key": "rain_today_raw_mm", "value": round(rain_today_mm, 3)})
        states.append({"key": "rain_today_date",   "value": datetime.date.today().isoformat()})

    rain_yesterday = obs.get("precip_accum_local_yesterday")
    if rain_yesterday is not None:
        _add_u(states, "rain_yesterday", float(rain_yesterday) * _UNIT_MM, "rain", unit_prefs)

    # Rain last 1 hour
    rain_1hr = obs.get("precip_accum_last_1hr")
    if rain_1hr is not None:
        _add_u(states, "rain_last_1hr", float(rain_1hr) * _UNIT_MM, "rain", unit_prefs)

    # Rain duration (minutes of measurable rain today / yesterday)
    rd_today = obs.get("precip_minutes_local_day")
    if rd_today is not None:
        states.append({"key": "rain_duration_today", "value": int(rd_today)})

    rd_yesterday = obs.get("precip_minutes_local_yesterday")
    if rd_yesterday is not None:
        states.append({"key": "rain_duration_yesterday", "value": int(rd_yesterday)})

    # Conditions text and icon name
    cond = obs.get("conditions")
    if cond is not None:
        states.append({"key": "conditions", "value": str(cond)})

    icon = obs.get("icon")
    if icon is not None:
        states.append({"key": "weather_icon", "value": str(icon)})

    # Hourly and 3-hour lightning counts
    lc_1hr = obs.get("lightning_strike_count_last_1hr")
    if lc_1hr is not None:
        states.append({"key": "lightning_count_last_1hr", "value": int(lc_1hr)})

    lc_3hr = obs.get("lightning_strike_count_last_3hr")
    if lc_3hr is not None:
        states.append({"key": "lightning_count_last_3hr", "value": int(lc_3hr)})

    if not include_standard:
        return states

    # --- Standard sensor states (web-only mode: no local UDP device) ---
    _add_u(states, "air_temperature",        _qty("air_temperature",    "degC"), "temp",     unit_prefs)
    _add_u(states, "temperature",            _qty("air_temperature",    "degC"), "temp",     unit_prefs)
    _add_u(states, "feels_like_temperature", _qty("feels_like",         "degC"), "temp",     unit_prefs)
    _add_u(states, "heat_index",             _qty("heat_index",         "degC"), "temp",     unit_prefs)
    _add_u(states, "wind_chill_temperature", _qty("wind_chill",         "degC"), "temp",     unit_prefs)
    _add_u(states, "dew_point_temperature",  _qty("dew_point",          "degC"), "temp",     unit_prefs)
    _add_u(states, "wet_bulb_temperature",   _qty("wet_bulb_temperature","degC"), "temp",    unit_prefs)

    rh = obs.get("relative_humidity")
    if rh is not None:
        _add_u(states, "relative_humidity", float(rh), "percent", unit_prefs)

    _add_u(states, "station_pressure",   _qty("station_pressure",  "mbar"), "pressure", unit_prefs)
    _add_u(states, "sea_level_pressure", _qty("sea_level_pressure","mbar"), "pressure", unit_prefs)

    _add_u(states, "wind_average",           _qty("wind_avg",       "m/s"), "wind",    unit_prefs)
    _add_u(states, "wind_speed",             _qty("wind_avg",       "m/s"), "wind",    unit_prefs)
    _add_u(states, "wind_gust",              _qty("wind_gust",      "m/s"), "wind",    unit_prefs)
    _add_u(states, "wind_lull",              _qty("wind_lull",      "m/s"), "wind",    unit_prefs)

    wind_dir = obs.get("wind_direction")
    if wind_dir is not None:
        _add_u(states, "wind_direction",         float(wind_dir), "degrees", unit_prefs)
        _add_u(states, "wind_direction_average", float(wind_dir), "degrees", unit_prefs)
        cardinal = _degrees_to_cardinal(float(wind_dir))
        states.append({"key": "wind_direction_cardinal",         "value": cardinal})
        states.append({"key": "wind_direction_average_cardinal", "value": cardinal})

    brightness = obs.get("brightness")
    if brightness is not None:
        _add_u(states, "illuminance", float(brightness), "lux", unit_prefs)

    solar = obs.get("solar_radiation")
    if solar is not None:
        _add_u(states, "solar_radiation", float(solar), "irradiance", unit_prefs)

    uv = obs.get("uv")
    if uv is not None:
        _add_u(states, "uv", float(uv), "uv", unit_prefs)

    # Last strike distance and energy from web data
    lsd = obs.get("lightning_strike_last_distance")
    if lsd is not None:
        _add_u(states, "last_strike_distance", _qty("lightning_strike_last_distance", "km"), "distance", unit_prefs)

    states.extend(_build_unit_states(unit_prefs))
    states.append({"key": "deviceStatus", "value": "Active (web)"})
    return states
