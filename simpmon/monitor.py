#!/usr/bin/env python3

import datetime
import logging
import os
import threading
import uuid
from abc import ABC, abstractmethod
from collections import deque
from typing import Optional, Sequence

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

    def run(self) -> None:
        datapoint = Point(y=self.get_datapoint(), x=datetime.datetime.now())
        self.datapoints.append(datapoint)
        if len(self.datapoints) > MAX_DATAPOINTS:
            self.datapoints.popleft()
        self.set_alarm_status()
        self._refresh_status()

    @abstractmethod
    def get_datapoint(self) -> float:
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
                    monitor.run()
                    if should_exit.is_set():
                        break
                should_exit.wait(self.granularity)
        except Exception as e:
            logger.critical(f"Unhandled exception in monitor: {e}")
            logger.debug("Exception info", exc_info=True)
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

    def get_datapoint(self) -> float:
        return os.getloadavg()[self.which]

    @property
    def unit(self) -> str:
        return "load"


MONITORS = {config.MonitorName.LOAD_AVERAGE: LoadAverageMonitor}


def get_monitors(configuration: config.Configuration) -> MonitorCollection:
    monitors = []
    for monitor_config in configuration.monitors:
        monitor_class = MONITORS.get(monitor_config.name)
        if monitor_class is None:
            message = f"Bug: Monitor {monitor_config.name.value} not implemented!"
            logger.critical(message)
            raise RuntimeError(message)
        monitors.append(monitor_class(monitor_config))
    return MonitorCollection(monitors, configuration.granularity)
