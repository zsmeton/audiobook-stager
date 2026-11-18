from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

JOB_ID = "audiobook_auto_stage"
_scheduler: BackgroundScheduler | None = None


def init_scheduler(tick: Callable[[], None], interval_hours: float) -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        tick,
        IntervalTrigger(hours=max(interval_hours, 0.25)),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Auto-stage scheduler started (every %s hours)", interval_hours)
    return scheduler


def reschedule_auto_job(tick: Callable[[], None], interval_hours: float) -> None:
    global _scheduler
    if _scheduler is None:
        init_scheduler(tick, interval_hours)
        return
    _scheduler.reschedule_job(
        JOB_ID,
        trigger=IntervalTrigger(hours=max(interval_hours, 0.25)),
    )
    logger.info("Auto-stage scheduler rescheduled (every %s hours)", interval_hours)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
