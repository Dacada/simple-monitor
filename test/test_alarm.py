#!/usr/bin/env python3

import pytest
from unittest.mock import MagicMock, patch
import uuid
import datetime
from simpmon.alarm import Alarmer, AlarmerAlarmInfo
from simpmon.monitor import MonitorStatus, Point
from simpmon.config import MonitorAlarmConfig, MonitorAlarmExceedanceType


# Define a concrete implementation of the abstract Alarmer class for testing
class TestAlarmer(Alarmer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ended_alarms = []
        self.started_alarms = []
        self.changed_alarms = []
        self.reminded_alarms = []

    def alarm_ended(self, alarm_info: AlarmerAlarmInfo) -> None:
        self.ended_alarms.append(alarm_info)

    def alarm_started(self, alarm_info: AlarmerAlarmInfo) -> None:
        self.started_alarms.append(alarm_info)

    def alarm_changed(
        self, prev_info: AlarmerAlarmInfo, next_info: AlarmerAlarmInfo
    ) -> None:
        self.changed_alarms.append((prev_info, next_info))

    def alarm_reminder(self, alarm_info: AlarmerAlarmInfo) -> None:
        self.reminded_alarms.append(alarm_info)


@pytest.fixture
def mock_monitor_collection():
    return MagicMock()


@pytest.fixture
def mock_configuration():
    mock_config = MagicMock()
    mock_config.name = "TestAlarmer"
    return mock_config


@pytest.fixture
def alarmer(mock_monitor_collection, mock_configuration):
    return TestAlarmer(
        configuration=mock_configuration,
        monitor_collection=mock_monitor_collection,
        node_name="test-node",
    )


def test_run_handles_new_alarms(alarmer, mock_monitor_collection):
    # Setup active alarm
    alarm_id = uuid.uuid4()
    active_alarm = MonitorAlarmConfig(
        name="HighLoad",
        count=1,
        value=80.0,
        exceedance=MonitorAlarmExceedanceType.OVER,
        reminder_age=datetime.timedelta(minutes=10),
    )
    status = MonitorStatus(
        id=alarm_id,
        name="LOAD_AVERAGE",
        title="Load Average",
        alarms=[],
        unit="%",
        values=(),
        active_alarm=active_alarm,
    )
    mock_monitor_collection.get_status.return_value = {alarm_id: status}

    # Run the method
    alarmer.run()

    # Assertions
    assert len(alarmer.started_alarms) == 1
    assert alarmer.started_alarms[0].monitor == status
    assert len(alarmer._current_alarms) == 1
    assert alarm_id in alarmer._current_alarms


def test_run_handles_ended_alarms(alarmer, mock_monitor_collection):
    # Setup existing alarm
    alarm_id = uuid.uuid4()
    active_alarm = MonitorAlarmConfig(
        name="HighLoad",
        count=1,
        value=80.0,
        exceedance=MonitorAlarmExceedanceType.OVER,
        reminder_age=datetime.timedelta(minutes=10),
    )
    status = MonitorStatus(
        id=alarm_id,
        name="LOAD_AVERAGE",
        title="Load Average",
        alarms=[],
        unit="%",
        values=(),
        active_alarm=active_alarm,
    )
    alarmer._current_alarms[alarm_id] = AlarmerAlarmInfo(
        id=alarm_id, monitor=status, last_alert=datetime.datetime.now()
    )

    # Simulate no active alarms now
    mock_monitor_collection.get_status.return_value = {}

    # Run the method
    alarmer.run()

    # Assertions
    assert len(alarmer.ended_alarms) == 1
    assert alarmer.ended_alarms[0].id == alarm_id
    assert len(alarmer._current_alarms) == 0


def test_run_handles_changed_alarms(alarmer, mock_monitor_collection):
    # Setup existing alarm
    alarm_id = uuid.uuid4()
    active_alarm_old = MonitorAlarmConfig(
        name="HighLoad",
        count=1,
        value=80.0,
        exceedance=MonitorAlarmExceedanceType.OVER,
        reminder_age=datetime.timedelta(minutes=10),
    )
    active_alarm_new = MonitorAlarmConfig(
        name="CriticalLoad",
        count=1,
        value=90.0,
        exceedance=MonitorAlarmExceedanceType.OVER,
        reminder_age=datetime.timedelta(minutes=5),
    )
    old_status = MonitorStatus(
        id=alarm_id,
        name="LOAD_AVERAGE",
        title="Load Average",
        alarms=[],
        unit="%",
        values=(),
        active_alarm=active_alarm_old,
    )
    new_status = MonitorStatus(
        id=alarm_id,
        name="LOAD_AVERAGE",
        title="Load Average",
        alarms=[],
        unit="%",
        values=(),
        active_alarm=active_alarm_new,
    )
    alarmer._current_alarms[alarm_id] = AlarmerAlarmInfo(
        id=alarm_id, monitor=old_status, last_alert=datetime.datetime.now()
    )

    # Simulate updated active alarm
    mock_monitor_collection.get_status.return_value = {alarm_id: new_status}

    # Run the method
    alarmer.run()

    # Assertions
    assert len(alarmer.changed_alarms) == 1
    assert alarmer.changed_alarms[0][0].monitor == old_status
    assert alarmer.changed_alarms[0][1].monitor == new_status


def test_run_handles_reminders(alarmer, mock_monitor_collection):
    # Setup existing alarm
    alarm_id = uuid.uuid4()
    active_alarm = MonitorAlarmConfig(
        name="HighLoad",
        count=1,
        value=80.0,
        exceedance=MonitorAlarmExceedanceType.OVER,
        reminder_age=datetime.timedelta(minutes=10),
    )
    status = MonitorStatus(
        id=alarm_id,
        name="LOAD_AVERAGE",
        title="Load Average",
        alarms=[],
        unit="%",
        values=(),
        active_alarm=active_alarm,
    )
    alarmer._current_alarms[alarm_id] = AlarmerAlarmInfo(
        id=alarm_id,
        monitor=status,
        last_alert=datetime.datetime.now() - datetime.timedelta(minutes=15),
    )

    # Simulate active alarm
    mock_monitor_collection.get_status.return_value = {alarm_id: status}

    # Run the method
    alarmer.run()

    # Assertions
    assert len(alarmer.reminded_alarms) == 1
    assert alarmer.reminded_alarms[0].monitor == status
    assert alarmer._current_alarms[
        alarm_id
    ].last_alert > datetime.datetime.now() - datetime.timedelta(seconds=1)
