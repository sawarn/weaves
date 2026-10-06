import logging
import os
import time
from typing import Optional

from weaves.db import (
    IS_POSTGRES,
    as_id,
    connect,
    initialize_database,
    json_value,
    statement,
)
from weaves.knowledge import search
from weaves.models import answer

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("weaves.worker")


def claim_job() -> Optional[dict]:
    with connect() as conn:
        if IS_POSTGRES:
            job = conn.execute(
                """SELECT j.id AS job_id, r.id AS run_id, r.task, r.agent_instructions
                   FROM jobs j JOIN runs r ON r.id = j.run_id
                   WHERE j.status = 'queued'
                   ORDER BY j.created_at
                   LIMIT 1 FOR UPDATE OF j SKIP LOCKED"""
            ).fetchone()
        else:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                """SELECT j.id AS job_id, r.id AS run_id, r.task, r.agent_instructions
                   FROM jobs j JOIN runs r ON r.id = j.run_id
                   WHERE j.status = 'queued' ORDER BY j.created_at LIMIT 1"""
            ).fetchone()
        if not job:
            return None
        conn.execute(
            statement(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1 WHERE id = %s"
            ),
            (job["job_id"],),
        )
        conn.execute(
            statement(
                "UPDATE runs SET status = 'running', started_at = now() WHERE id = %s"
            ),
            (as_id(job["run_id"]),),
        )
        return job


def execute(job: dict) -> None:
    try:
        sources = search(job["task"])
        text, model = answer(job["task"], sources, job["agent_instructions"])
        result = {
            "answer": text,
            "sources": [s["source"] for s in sources],
            "model": model,
        }
        with connect() as conn:
            conn.execute(
                statement(
                    "UPDATE runs SET status = 'succeeded', result = %s, finished_at = now() WHERE id = %s"
                ),
                (json_value(result), as_id(job["run_id"])),
            )
            conn.execute(
                statement("UPDATE jobs SET status = 'succeeded' WHERE id = %s"),
                (as_id(job["job_id"]),),
            )
        logger.info(
            "run completed run_id=%s source_count=%d", job["run_id"], len(sources)
        )
    except Exception as exc:
        logger.exception("run failed run_id=%s", job["run_id"])
        with connect() as conn:
            conn.execute(
                statement(
                    "UPDATE runs SET status = 'failed', error = %s, finished_at = now() WHERE id = %s"
                ),
                (str(exc)[:1000], as_id(job["run_id"])),
            )
            conn.execute(
                statement("UPDATE jobs SET status = 'failed' WHERE id = %s"),
                (as_id(job["job_id"]),),
            )


def main() -> None:
    initialize_database()
    interval = float(os.getenv("POLL_INTERVAL_SECONDS", "1"))
    logger.info("worker started poll_interval_seconds=%s", interval)
    while True:
        try:
            job = claim_job()
            if job:
                execute(job)
            else:
                time.sleep(interval)
        except Exception:
            logger.exception("worker loop error")
            time.sleep(interval)


if __name__ == "__main__":
    main()
