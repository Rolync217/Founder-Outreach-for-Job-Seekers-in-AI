"""
scheduler.py
APScheduler — fires the pipeline at 6 AM CT on the days defined in config.yaml.

Sending is manual (dashboard buttons). No automated send job runs here.

Run once and leave it running:
    python scheduler.py

To run immediately for testing:
    python scheduler.py --now
"""

import logging
import os
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

sys.path.insert(0, str(Path(__file__).parent))
from tools.config_loader import cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scheduler")

TZ = pytz.timezone(cfg["schedule"]["timezone"])

pipeline_hour, pipeline_min = map(int, cfg["schedule"]["pipeline_run_time"].split(":"))

_HEARTBEAT = Path("/tmp/scheduler_heartbeat")


def _touch_heartbeat():
    """Write a heartbeat file so Docker health checks can verify the scheduler is alive."""
    try:
        _HEARTBEAT.touch()
    except Exception:
        pass  # non-fatal — health check is best-effort


def run_pipeline():
    log.info("Triggering pipeline run...")
    from pipeline_v2.run import run_pipeline as _run_pipeline
    try:
        _run_pipeline(run_type="deep_run")
        log.info("Pipeline completed successfully.")
        _touch_heartbeat()
    except Exception as e:
        log.error(f"Pipeline failed: {e}", exc_info=True)


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=TZ)

    if not cfg["schedule"].get("pipeline_enabled", True):
        log.warning("Pipeline is DISABLED (pipeline_enabled: false in config.yaml) — no jobs scheduled.")
        return scheduler

    run_days = cfg["schedule"]["run_days"]

    scheduler.add_job(
        run_pipeline,
        CronTrigger(
            hour=pipeline_hour,
            minute=pipeline_min,
            day_of_week=run_days,
            timezone=TZ
        ),
        id="pipeline",
        name="Sourcing + research + scoring + drafting",
        misfire_grace_time=1800,   # tolerate up to 30 min late start
    )

    return scheduler


if __name__ == "__main__":
    log.info(f"Scheduler starting — pipeline: {pipeline_hour:02d}:{pipeline_min:02d} CT on {cfg['schedule']['run_days']}")
    log.info("Sending is manual via dashboard — no automated send job registered.")

    # Allow manual trigger with --now flag (for testing / backfill)
    if "--now" in sys.argv:
        log.info("--now flag: running pipeline immediately")
        run_pipeline()
        sys.exit(0)

    if "--smoke-test" in sys.argv:
        os.environ["SMOKE_TEST"] = "1"
        log.info("*** SMOKE TEST MODE — pool cap: 5 companies, cost cap: $2.00 ***")
        run_pipeline()
        sys.exit(0)

    if "--send-now" in sys.argv:
        log.info("--send-now flag: sending is manual via dashboard. No-op.")
        sys.exit(0)

    scheduler = build_scheduler()
    log.info("Scheduler running. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Scheduler stopped.")
