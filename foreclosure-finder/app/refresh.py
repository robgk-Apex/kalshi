"""Background re-scrape loop used by the hosted site (AUTO_REFRESH_HOURS)."""
import logging
import threading
import time

from . import db
from .scrapers import homepath, homesteps, hud

log = logging.getLogger("refresh")


def run_once():
    for name, mod in (("hud", hud), ("homepath", homepath), ("homesteps", homesteps)):
        try:
            started = time.time()
            listings = mod.scrape(None, details=True)
            if not listings:
                log.warning("[%s] refresh returned nothing; keeping existing rows", name)
                continue
            with db.connect() as c:
                for p in listings:
                    db.upsert_property(c, p)
                # Listings not seen in this run have sold or been pulled; drop them.
                c.execute("DELETE FROM properties WHERE source=? AND updated_at < ?",
                          (name, started))
            log.info("[%s] refreshed %d listings", name, len(listings))
        except Exception:
            log.exception("[%s] refresh failed", name)


def start(hours: float):
    def loop():
        time.sleep(60)  # let the server come up first
        while True:
            run_once()
            time.sleep(hours * 3600)
    threading.Thread(target=loop, daemon=True, name="refresh").start()
