#!/usr/bin/env python3

import datetime
import ipaddress
import json
import logging
from enum import Enum
from pathlib import Path
from typing import Literal, Optional, Union, cast

from pydantic import BaseModel, Field, field_validator
from typing_extensions import Annotated

from simpmon import paths


class MonitorName(str, Enum):
    LOAD_AVERAGE = "LOAD_AVERAGE"
    DISK_USAGE = "DISK_USAGE"
    DISK_WRITE_RATE = "DISK_WRITE_RATE"
    TEMPERATURE = "TEMPERATURE"
    UPTIME = "UPTIME"
    SYSTEMD = "SYSTEMD"
    PING = "PING"


class AlarmerName(str, Enum):
    GMAIL_ALARM = "GMAIL_ALARM"


class MonitorAlarmExceedanceType(str, Enum):
    UNDER = "UNDER"
    OVER = "OVER"


class DiskUsageValueType(str, Enum):
    TOTAL = "TOTAL"
    USED = "USED"
    FREE = "FREE"
    PERCENT = "PERCENT"


class MonitorAlarmConfig(BaseModel):
    name: str
    count: int
    value: float
    exceedance: MonitorAlarmExceedanceType
    reminder_age: Optional[datetime.timedelta]


class LoadAverageMonitorConfig(BaseModel):
    name: Literal[MonitorName.LOAD_AVERAGE]
    title: str
    alarms: list[MonitorAlarmConfig]
    which: Annotated[int, Field(ge=0, lt=3)]


class DiskUsageMonitorConfig(BaseModel):
    name: Literal[MonitorName.DISK_USAGE]
    title: str
    alarms: list[MonitorAlarmConfig]
    mountpoint: Path
    which: DiskUsageValueType
    unit_base: Literal[1000, 1024]
    unit_exponent: Annotated[int, Field(ge=0, le=5)]

    @field_validator("mountpoint")
    def validate_mountpoint(cls, value: Path) -> Path:
        if not value.is_mount():
            raise ValueError(f"The path '{value}' is not a mount point.")
        return value


class DiskWriteRateMonitorConfig(BaseModel):
    name: Literal[MonitorName.DISK_WRITE_RATE]
    title: str
    alarms: list[MonitorAlarmConfig]
    disk: str
    unit_base: Literal[1000, 1024]
    unit_exponent: Annotated[int, Field(ge=0, le=5)]


class TemperatureMonitorConfig(BaseModel):
    name: Literal[MonitorName.TEMPERATURE]
    title: str
    alarms: list[MonitorAlarmConfig]
    sensor_name: str
    index: int


class UptimeMonitorConfig(BaseModel):
    name: Literal[MonitorName.UPTIME]
    title: str
    alarms: list[MonitorAlarmConfig]


class SystemdMonitorConfig(BaseModel):
    name: Literal[MonitorName.SYSTEMD]
    title: str
    alarms: list[MonitorAlarmConfig]
    service: str


class PingMonitorConfig(BaseModel):
    name: Literal[MonitorName.PING]
    title: str
    alarms: list[MonitorAlarmConfig]
    ip: ipaddress.IPv4Address


class GmailAlarmerConfig(BaseModel):
    name: Literal[AlarmerName.GMAIL_ALARM]
    sender: str
    receiver: str
    server: str
    port: int
    app_password: str


MonitorConfig = Annotated[
    Union[
        LoadAverageMonitorConfig,
        DiskUsageMonitorConfig,
        DiskWriteRateMonitorConfig,
        TemperatureMonitorConfig,
        UptimeMonitorConfig,
        SystemdMonitorConfig,
        PingMonitorConfig,
    ],
    Field(discriminator="name"),
]
AlarmerConfig = Annotated[Union[GmailAlarmerConfig], Field(discriminator="name")]


class Configuration(BaseModel):
    class LogLevel(Enum):
        DEBUG = "DEBUG"
        INFO = "INFO"
        WARNING = "WARNING"
        ERROR = "ERROR"
        CRITICAL = "CRITICAL"

        def to_loglevel(self) -> int:
            return cast(int, getattr(logging, self.value))

    name: str = "Node name"
    loglevel: LogLevel = LogLevel.INFO
    monitors: list[MonitorConfig] = []
    alarms: list[AlarmerConfig] = []
    webui_port: int = 8080
    granularity: int = 5


def get_config() -> Configuration:
    config_path = paths.config_path()

    if config_path.exists():
        with open(config_path, "r") as f:
            json_data = json.load(f)
            return Configuration.model_validate(json_data)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    default = Configuration()
    with open(config_path, "w") as f:
        f.write(default.model_dump_json())
    return default
