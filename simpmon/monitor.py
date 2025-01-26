#!/usr/bin/env python3

import concurrent.futures
import datetime
import logging
import os
import subprocess
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from typing import Any, Callable, Optional, Sequence, Type

import dbus  # type: ignore
import ping3  # type: ignore
import psutil
from pydantic import BaseModel

from simpmon import config

MAX_DATAPOINTS = 100

logger = logging.getLogger(__name__)


class Point(BaseModel):
    x: datetime.datetime
    y: float


class MonitorStatus(BaseModel):
    id: uuid.UUID
    name: str
    title: str
    alarms: list[config.MonitorAlarmConfig]
    unit: str
    values: Sequence[Point]
    active_alarm: Optional[config.MonitorAlarmConfig]


class Monitor(ABC):
    def __init__(self, configuration: config.MonitorConfig):
        self.name = configuration.name
        self.title = configuration.title
        self._alarm_info = configuration.alarms
        self._over_alarms = sorted(
            (
                alarm
                for alarm in self._alarm_info
                if alarm.exceedance == config.MonitorAlarmExceedanceType.OVER
            ),
            key=lambda alarm: alarm.value,
            reverse=True,
        )
        self._under_alarms = sorted(
            (
                alarm
                for alarm in self._alarm_info
                if alarm.exceedance == config.MonitorAlarmExceedanceType.UNDER
            ),
            key=lambda alarm: alarm.value,
        )
        self.id = uuid.uuid4()
        self.active_alarm: Optional[config.MonitorAlarmConfig] = None
        self.datapoints: deque[Point] = deque()
        self._refresh_status()

    @property
    @abstractmethod
    def unit(self) -> str:
        pass

    def run(self, must_exit: threading.Event) -> None:
        datapoint = Point(y=self.get_datapoint(must_exit), x=datetime.datetime.now())
        self.datapoints.append(datapoint)
        if len(self.datapoints) > MAX_DATAPOINTS:
            self.datapoints.popleft()
        self.set_alarm_status()
        self._refresh_status()

    @abstractmethod
    def get_datapoint(self, must_exit: threading.Event) -> float:
        pass

    def set_alarm_status(self) -> None:
        active_alarm = None
        for alarm_list in (self._over_alarms, self._under_alarms):
            for alarm in alarm_list:
                if self._set_alarm_status(alarm):
                    active_alarm = alarm
                    break
            if active_alarm is not None:
                break

        if active_alarm != self.active_alarm:
            logger.info(
                f"{self.title} -- Alarm status changed "
                f"previous alarm was {None if self.active_alarm is None else self.active_alarm.name} "
                f"current alarm is {None if active_alarm is None else active_alarm.name}"
            )

        self.active_alarm = active_alarm

    def _set_alarm_status(self, alarm: config.MonitorAlarmConfig) -> bool:
        alarm_datapoints = set()
        for i in range(alarm.count):
            try:
                alarm_datapoints.add(self.datapoints[-i - 1].y)
            except IndexError:
                logger.warning(
                    f"{self.title} -- Insufficient data for alarm {alarm.name}"
                )
                return False

        activated = False
        if alarm.exceedance == config.MonitorAlarmExceedanceType.UNDER:
            activated = all(p < alarm.value for p in alarm_datapoints)
        if alarm.exceedance == config.MonitorAlarmExceedanceType.OVER:
            activated = all(p > alarm.value for p in alarm_datapoints)

        return activated

    def _refresh_status(self) -> None:
        logger.debug(
            f"Refresh status of {__name__}:\n"
            f"\tid={self.id}\n"
            f"\tname={self.name}\n"
            f"\ttitle={self.title}\n"
            f"\tunit={self.unit}\n"
            f"\tvalues=(...{','.join(str(self.datapoints[-i-1]) for i in range(min(3, len(self.datapoints))))})\n"
            f"\talarms={self._alarm_info}\n"
            f"\tactive_alarm={self.active_alarm}"
        )
        self.status = MonitorStatus(
            id=self.id,
            name=self.name,
            title=self.title,
            unit=self.unit,
            values=self.datapoints,
            alarms=self._alarm_info,
            active_alarm=self.active_alarm,
        )

    def get_status(self) -> MonitorStatus:
        return self.status


class MonitorCollection:
    def __init__(self, monitors: Sequence[Monitor], granularity: int):
        self._monitors = {monitor.id: monitor for monitor in monitors}
        self.granularity = granularity

    def run(self, should_exit: threading.Event) -> None:
        try:
            while not should_exit.is_set():
                for monitor in self._monitors.values():
                    monitor.run(should_exit)
                    if should_exit.is_set():
                        break
                should_exit.wait(self.granularity)
        except Exception as e:
            logger.critical(f"Unhandled exception in monitor: {e}", exc_info=True)
            should_exit.set()
            return

    def get_status(self) -> dict[uuid.UUID, MonitorStatus]:
        return {id: monitor.get_status() for id, monitor in self._monitors.items()}

    def get_status_json(self) -> str:
        part = ",".join(
            status.model_dump_json() for status in self.get_status().values()
        )
        return "[" + part + "]"


class LoadAverageMonitor(Monitor):
    def __init__(self, config: config.LoadAverageMonitorConfig):
        self.which = config.which
        super().__init__(config)

    def get_datapoint(self, must_exit: threading.Event) -> float:
        return os.getloadavg()[self.which]

    @property
    def unit(self) -> str:
        return "load"


def _make_unit(base: int, exponent: int) -> str:
    suffix = ["", "K", "M", "G", "T", "P"][exponent]
    infix = "i" if base == 1024 and suffix else ""
    return suffix + infix + "B"


class DiskUsageMonitor(Monitor):
    def __init__(self, config: config.DiskUsageMonitorConfig):
        self.mountpoint = config.mountpoint
        self.which = config.which
        self.divider = float(config.unit_base) ** config.unit_exponent
        self._unit = _make_unit(config.unit_base, config.unit_exponent)
        super().__init__(config)

    def get_datapoint(self, must_exit: threading.Event) -> float:
        usage = psutil.disk_usage(str(self.mountpoint))

        value = 0.0
        if self.which == config.DiskUsageValueType.FREE:
            value = usage.free / self.divider
        elif self.which == config.DiskUsageValueType.USED:
            value = usage.used / self.divider
        elif self.which == config.DiskUsageValueType.TOTAL:
            value = usage.total / self.divider
        elif self.which == config.DiskUsageValueType.PERCENT:
            value = usage.percent
        else:
            raise TypeError(f"Unexpected disk usage type: {self.which}")

        return value

    @property
    def unit(self) -> str:
        if self.which == config.DiskUsageValueType.PERCENT:
            return "%"
        return self._unit


class DiskWriteRateMonitor(Monitor):
    def __init__(self, config: config.DiskWriteRateMonitorConfig):
        self.disk = config.disk
        self.divider = float(config.unit_base) ** config.unit_exponent
        self._unit = _make_unit(config.unit_base, config.unit_exponent)
        self.warned_io_counters_unavailable = False
        self.last: Optional[tuple[datetime.datetime, int]] = None
        super().__init__(config)

    def get_datapoint(self, must_exit: threading.Event) -> float:
        if self.warned_io_counters_unavailable:
            return 0

        counter_info = psutil.disk_io_counters(True)
        if counter_info is None:
            logger.warning("I/O counters unavailable. Will always measure zero.")
            self.warned_io_counters_unavailable = True
            return 0

        current_time = datetime.datetime.now()
        current_value = counter_info[self.disk].write_bytes
        if self.last is None:
            self.last = (current_time, current_value)
            return 0

        prev_time, prev_value = self.last
        interval = current_time - prev_time
        difference = current_value - prev_value
        self.last = (current_time, current_value)

        return difference / interval.seconds / self.divider

    @property
    def unit(self) -> str:
        return self._unit + "/second"


class TemperatureMonitor(Monitor):
    def __init__(self, config: config.TemperatureMonitorConfig):
        self.sensor = config.sensor_name
        self.index = config.index
        self.warned_sensor_unavailable = False
        super().__init__(config)

    def get_datapoint(self, must_exit: threading.Event) -> float:
        if self.warned_sensor_unavailable:
            return 0

        sensors = psutil.sensors_temperatures()
        sensor_points = sensors.get(self.sensor)
        if sensor_points is None:
            logger.warning(
                f"Sensor {repr(self.sensor)} unavailable. You may need to install a temperature sensor utility. Will always measure zero."
            )
            self.warned_sensor_unavailable = True
            return 0

        if len(sensor_points) <= self.index:
            logger.warning(
                f"There are {len(sensor_points)} kinds of readings for sensor {repr(self.sensor)} but index {self.index} was given. Will always measure zero."
            )
            self.warned_sensor_unavailable = True
            return 0

        return sensor_points[self.index].current

    @property
    def unit(self) -> str:
        return "ºC"


class UptimeMonitor(Monitor):
    def __init__(self, config: config.UptimeMonitorConfig):
        super().__init__(config)

    def get_datapoint(self, must_exit: threading.Event) -> float:
        now = time.time()
        boot = psutil.boot_time()
        uptime = now - boot
        return uptime

    @property
    def unit(self) -> str:
        return "seconds"


class DBusConnectionManager:
    _bus = None

    @staticmethod
    def get_connection() -> Any:
        if DBusConnectionManager._bus is None:
            DBusConnectionManager._bus = dbus.SystemBus()
        return DBusConnectionManager._bus


class SystemdMonitor(Monitor):
    def __init__(self, config: config.SystemdMonitorConfig):
        self.service_name = config.service
        self.systemd_proxy: Any = None
        self._initialize_proxy()
        super().__init__(config)

    def _initialize_proxy(self) -> None:
        bus = DBusConnectionManager.get_connection()
        systemd_object = bus.get_object(
            "org.freedesktop.systemd1", "/org/freedesktop/systemd1"
        )
        self.systemd_proxy = dbus.Interface(
            systemd_object, dbus_interface="org.freedesktop.systemd1.Manager"
        )

    def get_datapoint(self, must_exit: threading.Event) -> float:
        try:
            unit_name = f"{self.service_name}.service"
            unit = self.systemd_proxy.GetUnit(unit_name)
            unit_object = DBusConnectionManager.get_connection().get_object(
                "org.freedesktop.systemd1", str(unit)
            )
            unit_properties = dbus.Interface(
                unit_object, dbus_interface="org.freedesktop.DBus.Properties"
            )

            active_state = unit_properties.Get(
                "org.freedesktop.systemd1.Unit", "ActiveState"
            )
            if active_state == "active":
                return 0
            elif active_state == "inactive":
                return 1
            elif active_state == "failed":
                return 2
            raise TypeError(f"Unexpected service state: {active_state}")
        except dbus.DBusException as e:
            print(f"Error retrieving status for service '{self.service_name}': {e}")
            return 1  # Assume stopped if there was an error

    @property
    def unit(self) -> str:
        return "status"


class ThreadManager:
    _thread_executor = None

    @staticmethod
    def submit(
        target: Callable[..., Any], must_exit: threading.Event
    ) -> concurrent.futures.Future[Any]:
        if ThreadManager._thread_executor is None:
            ThreadManager._thread_executor = concurrent.futures.ThreadPoolExecutor()
        return ThreadManager._thread_executor.submit(target, must_exit)


class PingMonitor(Monitor):
    def __init__(self, config: config.PingMonitorConfig):
        self.ip = config.ip
        self._last_ping = -1
        self._ping_future: Optional[concurrent.futures.Future[Any]] = None
        super().__init__(config)

    def _start_ping(self, must_exit: threading.Event) -> None:
        if self._ping_future is not None:
            return
        self._ping_future = ThreadManager.submit(self._run_ping, must_exit)

    def _run_ping(self, must_exit: threading.Event) -> None:
        try:
            response_time = ping3.ping(str(self.ip))
            if response_time is None:
                self._last_ping = -1
            self._last_ping = response_time
        except Exception as e:
            logger.warning(f"Exception when trying to ping to {self.ip}: {e}")
            self._last_ping = -1
        finally:
            self._ping_future = None

    def get_datapoint(self, must_exit: threading.Event) -> float:
        self._start_ping(must_exit)
        return self._last_ping * 1000

    @property
    def unit(self) -> str:
        return "miliseconds"


class PackageManagerMonitor(Monitor):
    def __init__(self, configuration: config.PackageManagerMonitorConfig):
        self._get_package_manager_upgradeable = {
            config.PackageManagerType.APT: self._get_apt_upgradeable,
            config.PackageManagerType.PACMAN: self._get_pacman_upgradeable,
        }[configuration.package_manager]
        self.delay = configuration.delay
        self.last_upgradeable = 0
        self._get_upgradeable_future: Optional[concurrent.futures.Future[Any]] = None
        super().__init__(configuration)

    def _get_apt_upgradeable(self) -> int:
        result = subprocess.run(
            ["apt", "list", "--upgradeable"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return sum(1 for line in result.stdout.splitlines() if "upgradeable" in line)

    def _get_pacman_upgradeable(self) -> int:
        result = subprocess.run(
            ["checkupdates"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return len(result.stdout.splitlines())

    def _start_get_upgradeable(self, must_exit: threading.Event) -> None:
        if self._get_upgradeable_future is not None:
            return
        self._get_upgradeable_future = ThreadManager.submit(
            self._run_get_upgradeable, must_exit
        )

    def _run_get_upgradeable(self, must_exit: threading.Event) -> None:
        try:
            self.last_upgradeable = self._get_package_manager_upgradeable()
        except Exception as e:
            logger.error(f"Exception when trying to get upgradeable packages: {e}")
        finally:
            must_exit.wait(self.delay)
            self._get_upgradeable_future = None

    def get_datapoint(self, must_exit: threading.Event) -> float:
        self._start_get_upgradeable(must_exit)
        return self.last_upgradeable

    @property
    def unit(self) -> str:
        return "packages"


MONITORS: dict[config.MonitorName, Type[Monitor]] = {
    config.MonitorName.LOAD_AVERAGE: LoadAverageMonitor,
    config.MonitorName.DISK_USAGE: DiskUsageMonitor,
    config.MonitorName.DISK_WRITE_RATE: DiskWriteRateMonitor,
    config.MonitorName.TEMPERATURE: TemperatureMonitor,
    config.MonitorName.UPTIME: UptimeMonitor,
    config.MonitorName.SYSTEMD: SystemdMonitor,
    config.MonitorName.PING: PingMonitor,
    config.MonitorName.PACKAGE_MANAGER: PackageManagerMonitor,
}


def get_monitors(configuration: config.Configuration) -> MonitorCollection:
    monitors = []
    for monitor_config in configuration.monitors:
        monitor_class = MONITORS.get(monitor_config.name)
        if monitor_class is None:
            message = f"Bug: Monitor {monitor_config.name.value} not implemented!"
            logger.critical(message)
            raise RuntimeError(message)
        monitor = monitor_class(monitor_config)
        monitors.append(monitor)
    return MonitorCollection(monitors, configuration.granularity)
