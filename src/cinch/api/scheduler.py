"""Discovery scheduler wiring (composition root).

Kept out of ``services/`` because it wires together concrete adapters — the LLM
provider, the job source, and the Telegram notifier — around the pure
:class:`~cinch.services.discovery.DiscoveryService`. ``run_discovery_cycle`` is the
DI-friendly entrypoint APScheduler calls; it takes its dependencies as arguments so
it can later run under Celery/Redis unchanged.
"""

from __future__ import annotations

from typing import Any

from telegram import Bot

from cinch.bot.notify import TelegramNotifier
from cinch.core.config import Settings
from cinch.core.logging import get_logger
from cinch.db.session import Database
from cinch.providers.jobs import get_job_source
from cinch.providers.llm import get_llm_provider
from cinch.services.discovery import DiscoveryService, DiscoverySummary
from cinch.services.tailoring import TailoringService

logger = get_logger(__name__)


async def run_discovery_cycle(db: Database, settings: Settings, bot: Bot) -> DiscoverySummary:
    """Build the pipeline and run one idempotent discovery cycle."""
    job_source = get_job_source(settings)
    tailoring = TailoringService(get_llm_provider(settings), settings)
    notifier = TelegramNotifier(bot)
    async with db.session() as session:
        service = DiscoveryService(
            session,
            job_source=job_source,
            tailoring=tailoring,
            notifier=notifier,
            settings=settings,
        )
        return await service.run()


def start_discovery_scheduler(db: Database, settings: Settings, bot: Bot) -> Any:
    """Create, start, and return an AsyncIOScheduler running the discovery cycle.

    One interval job, non-overlapping (``max_instances=1``, ``coalesce=True``). The
    caller owns shutdown. Imported lazily so APScheduler is only required when
    discovery is actually enabled.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_discovery_cycle,
        trigger="interval",
        minutes=settings.discovery_interval_minutes,
        args=[db, settings, bot],
        id="discovery",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("discovery_scheduler_started", interval_minutes=settings.discovery_interval_minutes)
    return scheduler
