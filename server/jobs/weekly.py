"""Weekly re-check, run by the Replit Scheduled deployment.

    python -m server.jobs.weekly

Checks every site with weekly_check on, one site at a time.
"""

import asyncio
import logging

from .. import repo
from ..config import get_settings
from ..crawler.run import execute_run
from ..db import init_db
from ..storage import get_store

log = logging.getLogger("weekly")


async def main() -> None:
    settings = get_settings()
    init_db()
    store = get_store(settings)
    sites = repo.sites_for_weekly()
    log.info("Weekly check: %s sites", len(sites))
    for site in sites:
        run_id = repo.create_run(site["id"], "scheduled")
        log.info("Checking %s (run %s)", site["root_url"], run_id)
        await execute_run(run_id, settings, store)
    log.info("Weekly check finished")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
