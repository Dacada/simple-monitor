#!/usr/bin/env python3

import datetime
import json
import logging
from enum import Enum
from typing import Literal, Optional, Union, cast

from pydantic import BaseModel, Field
from typing_extensions import Annotated

from simpmon import paths


class MonitorName(str, Enum):
    LOAD_AVERAGE = "LOAD_AVERAGE"


class AlarmerName(str, Enum):
    GMAIL_ALARM = "GMAIL_ALARM"


class MonitorAlarmExceedanceType(str, Enum):
    UNDER = "UNDER"
    OVER = "OVER"


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


class GmailAlarmerConfig(BaseModel):
    name: Literal[AlarmerName.GMAIL_ALARM]
    sender: str
    receiver: str
    server: str
    port: int
    app_password: str


MonitorConfig = Annotated[Union[LoadAverageMonitorConfig], Field(discriminator="name")]
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
