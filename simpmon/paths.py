#!/usr/bin/env python3

import os
from pathlib import Path


def appname() -> Path:
    return Path("simpmon")


def home() -> Path:
    return Path.home()


def dir_home(envvar: str, fallback: Path) -> Path:
    from_env = os.getenv(envvar)
    if from_env is None:
        return home() / fallback
    return Path(from_env)


def config_home() -> Path:
    if os.geteuid() == 0:
        return Path("/etc")
    return dir_home("XDG_CONFIG_HOME", Path(".config"))


def log_home() -> Path:
    if os.geteuid() == 0:
        return Path("/var/log")
    return dir_home("XDG_DATA_HOME", Path(".local/share"))


def config_path() -> Path:
    return config_home() / appname() / "config.json"


def log_path() -> Path:
    return log_home() / appname() / "log.txt"
