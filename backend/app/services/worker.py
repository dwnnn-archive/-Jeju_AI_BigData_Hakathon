"""Single-host queue runner. The leader lock is held for this worker's lifetime."""

import logging
import sqlite3
import threading

from filelock import Timeout

logger = logging.getLogger(__name__)


def start_worker(service):
    def run():
        while not service.stop.is_set():
            try:
                with service.execution_lock:
                    service.recover()
                    while not service.stop.is_set():
                        worked = service.run_once()
                        service.worker_error = None
                        if not worked:
                            service.wake.wait(0.5)
                            service.wake.clear()
            except Timeout:
                service.stop.wait(1)
            except sqlite3.OperationalError:
                service.worker_error = "database_temporarily_unavailable"
                logger.warning("Worker database operation failed; recovery will retry")
                service.stop.wait(1)
            except Exception:
                service.worker_error = "worker_stopped"
                logger.exception("Worker stopped unexpectedly")
                return

    service.runner = threading.Thread(target=run, name="analysis-worker", daemon=True)
    service.runner.start()
