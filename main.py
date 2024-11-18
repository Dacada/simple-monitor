#!/usr/bin/env python3

import logging
import os
import signal
import threading
from typing import Any

from simpmon import alarm, config, logs, monitor, webui

logger = logging.getLogger(__name__)


def main() -> int:
    configuration = config.get_config()
    logs.setup(configuration)

    logger.info("Starting up...")
    monitors = monitor.get_monitors(configuration)
    run_webui = webui.setup_webui(configuration, monitors)
    alarm_manager = alarm.get_alarm_manager(configuration, monitors)

    must_exit = threading.Event()

    threads = []
    threads.append(threading.Thread(target=monitors.run, args=(must_exit,)))
    threads.append(threading.Thread(target=run_webui, args=(must_exit,)))
    threads.append(threading.Thread(target=alarm_manager.run, args=(must_exit,)))

    def exit_handler(*_: Any) -> None:
        logging.info("Exit signal received.")
        if must_exit.is_set():
            logging.warning("Forcing exit!")
            os._exit(1)
        must_exit.set()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, exit_handler)

    logger.info("Starting threads...")
    for thread in threads:
        thread.start()

    logger.info("Looping...")
    must_exit.wait()
    logger.info("Joining threads and exiting.")

    for thread in threads:
        thread.join()

    return 0


if __name__ == "__main__":
    exit(main())
