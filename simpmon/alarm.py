#!/usr/bin/env python3

import datetime
import logging
import smtplib
import threading
import uuid
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Sequence

from pydantic import BaseModel

from simpmon import config, monitor

logger = logging.getLogger(__name__)


class AlarmerAlarmInfo(BaseModel):
    id: uuid.UUID
    monitor: monitor.MonitorStatus
    last_alert: datetime.datetime


class Alarmer(ABC):
    def __init__(
        self,
        configuration: config.AlarmerConfig,
        monitor_collection: monitor.MonitorCollection,
        node_name: str,
    ) -> None:
        self.node_name = node_name
        self.monitor_collection = monitor_collection
        self.name = configuration.name
        self._current_alarms: dict[uuid.UUID, AlarmerAlarmInfo] = {}

    @abstractmethod
    def alarm_ended(self, alarm_info: AlarmerAlarmInfo) -> None:
        pass

    @abstractmethod
    def alarm_started(self, alarm_info: AlarmerAlarmInfo) -> None:
        pass

    @abstractmethod
    def alarm_changed(
        self, prev_info: AlarmerAlarmInfo, next_info: AlarmerAlarmInfo
    ) -> None:
        pass

    @abstractmethod
    def alarm_reminder(self, alarm_info: AlarmerAlarmInfo) -> None:
        pass

    def run(self) -> None:
        now = datetime.datetime.now()
        statuses = self.monitor_collection.get_status()
        alarmed_statuses = {
            id: monitor.MonitorStatus(
                id=status.id,
                name=status.name,
                title=status.title,
                alarms=[],
                unit=status.unit,
                values=(),
                active_alarm=status.active_alarm,
            )
            for id, status in statuses.items()
            if status.active_alarm is not None
        }

        # Remove known alarms that aren't active anymore
        to_remove = set()
        for id in self._current_alarms:
            if id not in alarmed_statuses:
                to_remove.add(id)

        for id in to_remove:
            self.alarm_ended(self._current_alarms[id])
            logger.debug(f"Remove alarm {id}")
            del self._current_alarms[id]

        # Go through monitors that were tracked already but now have a different alarm
        for id, monitor_status in alarmed_statuses.items():
            if id not in self._current_alarms:
                continue
            known_alarm = self._current_alarms[id]
            if monitor_status.active_alarm != known_alarm.monitor.active_alarm:
                logger.debug(f"Update alarm {id}")
                new_known_alarm = AlarmerAlarmInfo(
                    id=id, last_alert=now, monitor=monitor_status
                )
                self.alarm_changed(known_alarm, new_known_alarm)
                self._current_alarms[id] = new_known_alarm

        # Add new alarms that weren't active before
        for id, monitor_status in alarmed_statuses.items():
            known_alarm = AlarmerAlarmInfo(
                id=id,
                monitor=monitor_status,
                last_alert=now,
            )
            if id not in self._current_alarms:
                logger.debug(f"Start alarm {id}")
                self.alarm_started(known_alarm)
                self._current_alarms[id] = known_alarm

        # Remind about alarms that haven't been alerted in a while
        for known_alarm in self._current_alarms.values():
            if known_alarm.monitor.active_alarm is None:
                logger.warning("Bug! We're tracking a monitor without an active alarm!")
                continue

            if known_alarm.monitor.active_alarm.reminder_age is None:
                continue

            if (
                now - known_alarm.last_alert
                > known_alarm.monitor.active_alarm.reminder_age
            ):
                known_alarm.last_alert = now
                logger.debug(f"Remind alarm {known_alarm.id}")
                self.alarm_reminder(known_alarm)


class EmailAlarmer(Alarmer):
    def __init__(
        self,
        configuration: config.GmailAlarmerConfig,
        monitor_collection: monitor.MonitorCollection,
        node_name: str,
    ) -> None:
        self.sender = configuration.sender
        self.receiver = configuration.receiver
        self.server = configuration.server
        self.port = configuration.port
        self.app_password = configuration.app_password
        super().__init__(configuration, monitor_collection, node_name)

    def alarm_ended(self, alarm_info: AlarmerAlarmInfo) -> None:
        if alarm_info.monitor.active_alarm is None:
            logger.warning("Bug! We're tracking a monitor without an active alarm!")
            return
        alarm = alarm_info.monitor.active_alarm
        monitor = alarm_info.monitor

        subject = f"Alarm ended for {alarm.name} on {self.node_name}"
        message = f"The alarm has ended for {monitor.title} ({monitor.name}) on node '{self.node_name}'"
        self.send_email(subject, message)

    def alarm_started(self, alarm_info: AlarmerAlarmInfo) -> None:
        if alarm_info.monitor.active_alarm is None:
            logger.warning("Bug! We're tracking a monitor without an active alarm!")
            return
        alarm = alarm_info.monitor.active_alarm
        monitor = alarm_info.monitor

        subject = f"Alarm triggered for {alarm.name} on {self.node_name}!"
        message = (
            f"An alarm has been triggered for {monitor.title} ({monitor.name}) on node '{self.node_name}'!\n"
            f"The value ({monitor.unit}) has gone {alarm.exceedance.value} {alarm.value} for {alarm.count} datapoints."
        )
        self.send_email(subject, message)

    def alarm_changed(
        self, prev_info: AlarmerAlarmInfo, next_info: AlarmerAlarmInfo
    ) -> None:
        if prev_info.monitor.active_alarm is None:
            logger.warning("Bug! We're tracking a monitor without an active alarm!")
            return
        prev_alarm = prev_info.monitor.active_alarm

        if next_info.monitor.active_alarm is None:
            logger.warning("Bug! We're tracking a monitor without an active alarm!")
            return
        next_alarm = next_info.monitor.active_alarm
        monitor = next_info.monitor

        subject = f"Alarm changed from {prev_alarm.name} to {next_alarm.name} on {self.node_name}!"
        message = (
            f"An alarm has changed for {monitor.title} ({monitor.name}) on node '{self.node_name}'!\n"
            f"The value ({monitor.unit}) has gone from being "
            f"{prev_alarm.exceedance.value} {prev_alarm.value} for {prev_alarm.count} datapoints "
            "to being"
            f"{next_alarm.exceedance.value} {next_alarm.value} for {next_alarm.count} datapoints."
        )
        self.send_email(subject, message)

    def alarm_reminder(self, alarm_info: AlarmerAlarmInfo) -> None:
        if alarm_info.monitor.active_alarm is None:
            logger.warning("Bug! We're tracking a monitor without an active alarm!")
            return
        alarm = alarm_info.monitor.active_alarm
        monitor = alarm_info.monitor

        subject = f"Alarm reminder for {alarm.name} on {self.node_name}!"
        message = (
            f"An alarm is still active for {monitor.title} ({monitor.name})!\n"
            f"The value ({monitor.unit}) is {alarm.exceedance.value} {alarm.value}.\n"
            f"This reminder's period is set to be: {alarm.reminder_age}."
        )
        self.send_email(subject, message)

    def send_email(self, subject: str, message: str) -> None:
        msg = MIMEMultipart()
        msg["From"] = self.sender
        msg["To"] = self.receiver
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain"))

        server = smtplib.SMTP(self.server, self.port)
        try:
            server.starttls()
            server.login(self.sender, self.app_password)
            server.sendmail(self.sender, self.receiver, msg.as_string())
            logger.info(f"Sent email to {self.receiver}")
        except Exception as e:
            logger.error(f"Failed to send email to {self.receiver}! Error: {e}")
            logger.debug("Exception info.", exc_info=True)
        finally:
            server.quit()


class AlarmManager:
    def __init__(self, alarmers: Sequence[Alarmer], granularity: int):
        self._alarmers = alarmers
        self.granularity = granularity

    def run(self, must_exit: threading.Event) -> None:
        try:
            while not must_exit.is_set():
                for alarmer in self._alarmers:
                    alarmer.run()
                    if must_exit.is_set():
                        break
                must_exit.wait(self.granularity)
        except Exception as e:
            logger.critical(f"Unhandled exception in monitor {e}")
            logger.debug("Exception info", exc_info=True)
            must_exit.set()
            return


ALARMERS = {config.AlarmerName.GMAIL_ALARM: EmailAlarmer}


def get_alarm_manager(
    configuration: config.Configuration, monitor_collection: monitor.MonitorCollection
) -> AlarmManager:
    alarmers = []
    for alarm_config in configuration.alarms:
        alarmer_class = ALARMERS.get(alarm_config.name)
        if alarmer_class is None:
            message = f"Bug: Alarmer {alarm_config.name.value} not implemented!"
            logger.critical(message)
            raise RuntimeError(message)
        alarmers.append(
            alarmer_class(alarm_config, monitor_collection, configuration.name)
        )
    return AlarmManager(alarmers, configuration.granularity)
