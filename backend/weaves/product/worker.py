"""Poll the durable product execution queue using the configured runtime."""

import logging
import os
import socket
import time
from uuid import uuid4

from weaves.product.runtime.service import LocalPlatformRuntime

logger = logging.getLogger("weaves.product.worker")


def main() -> None:
    interval = float(os.environ.get("WEAVES_WORKER_POLL_SECONDS", "1"))
    if not 0.05 <= interval <= 60:
        raise ValueError("WEAVES_WORKER_POLL_SECONDS must be between 0.05 and 60")
    schedule_interval = float(os.environ.get("WEAVES_SCHEDULE_POLL_SECONDS", "5"))
    if not 0.5 <= schedule_interval <= 60:
        raise ValueError("WEAVES_SCHEDULE_POLL_SECONDS must be between 0.5 and 60")
    worker_id = os.environ.get("WEAVES_WORKER_ID", "").strip()
    worker_id = worker_id or f"{socket.gethostname()}-{uuid4().hex[:12]}"
    runtime = LocalPlatformRuntime()
    try:
        if runtime.storage_mode != "postgres":
            raise RuntimeError("The execution worker requires DATABASE_URL")
        runtime.bootstrap()
        logger.info("product execution worker started worker_id=%s", worker_id)
        last_recovery = time.monotonic()
        last_schedule_poll = 0.0
        while True:
            try:
                if time.monotonic() - last_recovery >= 30:
                    runtime.recover_stale_runs()
                    recovered_jobs = runtime.recover_stale_execution_jobs()
                    recovered_actions = runtime.recover_stale_action_invocations()
                    if recovered_jobs:
                        logger.warning(
                            "recovered stale execution jobs count=%d",
                            len(recovered_jobs),
                        )
                    if recovered_actions:
                        logger.warning(
                            "recovered stale action invocations count=%d",
                            len(recovered_actions),
                        )
                    expired_memory = runtime.purge_expired_memory_items()
                    if expired_memory:
                        logger.info(
                            "purged expired memory items count=%d",
                            len(expired_memory),
                        )
                    last_recovery = time.monotonic()
                if time.monotonic() - last_schedule_poll >= schedule_interval:
                    scheduled_jobs = runtime.dispatch_due_workflow_schedules()
                    if scheduled_jobs:
                        logger.info(
                            "workflow schedules dispatched count=%d",
                            len(scheduled_jobs),
                        )
                    last_schedule_poll = time.monotonic()
                job = runtime.process_next_execution_job(worker_id)
                if job is None:
                    time.sleep(interval)
                    continue
                logger.info(
                    "product execution job finished job_id=%s status=%s run_id=%s",
                    job.job_id,
                    job.status.value,
                    job.run_id,
                )
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.exception("product execution worker iteration failed")
                time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("product execution worker stopped worker_id=%s", worker_id)
    finally:
        runtime.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    main()
