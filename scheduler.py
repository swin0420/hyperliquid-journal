"""Background task scheduler for periodic trade syncing."""

import logging
import threading
from typing import Callable
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Scheduler instance
_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()

# Default sync interval in minutes
DEFAULT_SYNC_INTERVAL = 5

# Track registered wallets for background sync
_registered_wallets: set[str] = set()
_wallet_lock = threading.Lock()


def get_scheduler() -> BackgroundScheduler:
    """Get or create the background scheduler (singleton)."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = BackgroundScheduler(
                job_defaults={
                    'coalesce': True,  # Combine missed runs into one
                    'max_instances': 1,  # Only one instance of each job at a time
                    'misfire_grace_time': 60  # Allow 60s grace period for misfires
                }
            )
        return _scheduler


def start_scheduler() -> None:
    """Start the background scheduler if not already running."""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("Background scheduler started")


def stop_scheduler() -> None:
    """Stop the background scheduler gracefully."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=True)
            logger.info("Background scheduler stopped")
            _scheduler = None


def register_wallet_for_sync(
    wallet_address: str,
    sync_func: Callable[[str], None],
    interval_minutes: int = DEFAULT_SYNC_INTERVAL
) -> bool:
    """
    Register a wallet for periodic background sync.

    Args:
        wallet_address: The wallet to sync
        sync_func: Function to call for syncing (takes wallet address)
        interval_minutes: How often to sync

    Returns:
        True if newly registered, False if already registered
    """
    wallet = wallet_address.lower()

    with _wallet_lock:
        if wallet in _registered_wallets:
            return False
        _registered_wallets.add(wallet)

    scheduler = get_scheduler()
    job_id = f"sync_{wallet}"

    # Add job for this wallet
    scheduler.add_job(
        func=sync_func,
        trigger=IntervalTrigger(minutes=interval_minutes),
        args=[wallet],
        id=job_id,
        replace_existing=True,
        name=f"Sync trades for {wallet[:10]}..."
    )

    logger.info("Registered wallet %s for background sync every %d minutes", wallet[:10], interval_minutes)
    return True


def unregister_wallet(wallet_address: str) -> bool:
    """
    Remove a wallet from background sync.

    Args:
        wallet_address: The wallet to unregister

    Returns:
        True if removed, False if not found
    """
    wallet = wallet_address.lower()

    with _wallet_lock:
        if wallet not in _registered_wallets:
            return False
        _registered_wallets.discard(wallet)

    scheduler = get_scheduler()
    job_id = f"sync_{wallet}"

    try:
        scheduler.remove_job(job_id)
        logger.info("Unregistered wallet %s from background sync", wallet[:10])
        return True
    except Exception:
        return False


def get_registered_wallets() -> list[str]:
    """Get list of wallets registered for background sync."""
    with _wallet_lock:
        return list(_registered_wallets)


def is_wallet_registered(wallet_address: str) -> bool:
    """Check if a wallet is registered for background sync."""
    with _wallet_lock:
        return wallet_address.lower() in _registered_wallets
