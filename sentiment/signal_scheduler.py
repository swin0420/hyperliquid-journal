"""Scheduler for periodic sentiment analysis polling.

Coordinates news fetching, analysis, and alert delivery.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.executors.pool import ThreadPoolExecutor

from .aggregator import NewsAggregator, NewsItem
from .analyzer import SentimentAnalyzer, SentimentResult
from .discord_bot import DiscordWebhook
from .models import (
    init_sentiment_db,
    get_sentiment_session,
    SignalRepository,
    BotStatusRepository
)

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_POLL_INTERVAL = 300  # 5 minutes
MIN_POLL_INTERVAL = 60  # 1 minute minimum
MAX_POLL_INTERVAL = 3600  # 1 hour maximum


class SentimentBot:
    """
    Sentiment analysis bot that polls news sources and sends alerts.

    Coordinates:
    - News aggregation from multiple sources
    - AI sentiment analysis via Claude
    - Discord alert delivery
    - Signal history persistence
    """

    def __init__(
        self,
        database_url: str,
        anthropic_api_key: str,
        discord_webhook_url: str,
        cryptopanic_api_key: Optional[str] = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        bot_name: str = "Sentiment Bot"
    ):
        """
        Initialize the sentiment bot.

        Args:
            database_url: PostgreSQL connection string
            anthropic_api_key: Anthropic API key for Claude
            discord_webhook_url: Discord webhook URL
            cryptopanic_api_key: Optional CryptoPanic API key
            poll_interval: Seconds between polls (default 300)
            bot_name: Display name for Discord messages
        """
        # Validate required params
        if not database_url:
            raise ValueError("database_url is required")
        if not anthropic_api_key:
            raise ValueError("anthropic_api_key is required")
        if not discord_webhook_url:
            raise ValueError("discord_webhook_url is required")

        # Validate poll interval
        self.poll_interval = max(MIN_POLL_INTERVAL, min(poll_interval, MAX_POLL_INTERVAL))

        # Initialize components
        self._db_url = database_url
        self._db_initialized = False

        self.aggregator = NewsAggregator(
            cryptopanic_api_key=cryptopanic_api_key,
            filter_by_assets=True
        )

        self.analyzer = SentimentAnalyzer(api_key=anthropic_api_key)

        self.discord = DiscordWebhook(
            webhook_url=discord_webhook_url,
            bot_name=bot_name
        )

        # Scheduler
        self._scheduler: Optional[BackgroundScheduler] = None
        self._job_id = "sentiment_poll"
        self._is_running = False
        self._lock = threading.Lock()

        # Stats
        self._total_polls = 0
        self._total_signals = 0
        self._total_alerts = 0
        self._last_poll_at: Optional[datetime] = None
        self._last_error: Optional[str] = None

    def _ensure_db(self) -> bool:
        """Ensure database is initialized."""
        if not self._db_initialized:
            self._db_initialized = init_sentiment_db(self._db_url)
        return self._db_initialized

    def _get_scheduler(self) -> BackgroundScheduler:
        """Get or create the scheduler."""
        if self._scheduler is None:
            executors = {
                'default': ThreadPoolExecutor(max_workers=1)
            }
            self._scheduler = BackgroundScheduler(
                executors=executors,
                job_defaults={
                    'coalesce': True,
                    'max_instances': 1,
                    'misfire_grace_time': 120
                }
            )
        return self._scheduler

    def _poll_and_analyze(self) -> None:
        """
        Main polling loop - fetch news, analyze, send alerts.

        Called by the scheduler at each interval.
        """
        try:
            logger.info("Starting sentiment poll...")
            self._total_polls += 1
            self._last_poll_at = datetime.now(timezone.utc)

            # Ensure DB is ready
            if not self._ensure_db():
                raise RuntimeError("Database not initialized")

            # Fetch new news
            news_items = self.aggregator.get_new_items(limit_per_source=20)
            if not news_items:
                logger.info("No new news items found")
                return

            logger.info("Fetched %d new news items", len(news_items))

            # Filter out already-processed news
            session = get_sentiment_session()
            if not session:
                raise RuntimeError("Could not get database session")

            try:
                repo = SignalRepository(session)
                new_items = [item for item in news_items if not repo.news_exists(item.id)]

                if not new_items:
                    logger.info("All news items already processed")
                    session.close()
                    return

                logger.info("Processing %d new items", len(new_items))

                # Analyze sentiment
                results = self.analyzer.get_actionable_signals(new_items)
                logger.info("Found %d actionable signals", len(results))

                # Save all news and signals to DB
                news_map = {item.id: item for item in new_items}
                url_map = {item.id: item.url for item in new_items}

                for item in new_items:
                    repo.save_news(item)

                for result in results:
                    news_item = news_map.get(result.news_id)
                    record = repo.save_signal(result, news_item)
                    self._total_signals += 1

                session.commit()

                # Send alerts for actionable signals
                if results:
                    sent = self.discord.send_batch_alerts(results, news_urls=url_map)
                    self._total_alerts += sent

                    # Mark alerts as sent
                    from .models import SignalRecord
                    for result in results:
                        signal = session.query(SignalRecord).filter_by(news_id=result.news_id).first()
                        if signal:
                            repo.mark_alert_sent(signal.id, "discord")

                    session.commit()
                    logger.info("Sent %d alerts to Discord", sent)

                # Clear last error on success
                self._last_error = None

            finally:
                session.close()

        except Exception as e:
            self._last_error = str(e)
            logger.exception("Error in sentiment poll: %s", e)

            # Try to send error to Discord
            try:
                self.discord.send_error(f"Poll error: {str(e)[:500]}")
            except Exception:
                pass

    def start(self, send_startup_message: bool = True) -> bool:
        """
        Start the sentiment bot.

        Args:
            send_startup_message: Whether to send startup message to Discord

        Returns:
            True if started successfully
        """
        with self._lock:
            if self._is_running:
                logger.warning("Sentiment bot is already running")
                return False

            try:
                # Initialize database
                if not self._ensure_db():
                    raise RuntimeError("Failed to initialize database")

                # Start scheduler
                scheduler = self._get_scheduler()

                scheduler.add_job(
                    func=self._poll_and_analyze,
                    trigger=IntervalTrigger(seconds=self.poll_interval),
                    id=self._job_id,
                    replace_existing=True,
                    name="Sentiment Poll"
                )

                if not scheduler.running:
                    scheduler.start()

                self._is_running = True
                logger.info("Sentiment bot started (poll interval: %ds)", self.poll_interval)

                # Send startup message
                if send_startup_message:
                    self.discord.send_startup_message()

                # Run first poll immediately
                threading.Thread(target=self._poll_and_analyze, daemon=True).start()

                return True

            except Exception as e:
                logger.exception("Failed to start sentiment bot: %s", e)
                return False

    def stop(self, send_shutdown_message: bool = True) -> bool:
        """
        Stop the sentiment bot.

        Args:
            send_shutdown_message: Whether to send shutdown message to Discord

        Returns:
            True if stopped successfully
        """
        with self._lock:
            if not self._is_running:
                logger.warning("Sentiment bot is not running")
                return False

            try:
                # Remove job
                scheduler = self._get_scheduler()
                if scheduler.get_job(self._job_id):
                    scheduler.remove_job(self._job_id)

                self._is_running = False
                logger.info("Sentiment bot stopped")

                # Send shutdown message
                if send_shutdown_message:
                    self.discord.send_shutdown_message()

                return True

            except Exception as e:
                logger.exception("Failed to stop sentiment bot: %s", e)
                return False

    def is_running(self) -> bool:
        """Check if the bot is running."""
        return self._is_running

    def get_stats(self) -> dict:
        """Get bot statistics."""
        return {
            "is_running": self._is_running,
            "poll_interval": self.poll_interval,
            "total_polls": self._total_polls,
            "total_signals": self._total_signals,
            "total_alerts": self._total_alerts,
            "last_poll_at": self._last_poll_at.isoformat() if self._last_poll_at else None,
            "last_error": self._last_error
        }

    def poll_now(self) -> dict:
        """
        Trigger an immediate poll.

        Returns:
            Dict with poll results
        """
        if not self._is_running:
            return {"error": "Bot is not running"}

        try:
            self._poll_and_analyze()
            return {
                "success": True,
                "last_poll_at": self._last_poll_at.isoformat() if self._last_poll_at else None
            }
        except Exception as e:
            return {"error": str(e)}

    def set_poll_interval(self, seconds: int) -> bool:
        """
        Update the poll interval.

        Args:
            seconds: New interval in seconds

        Returns:
            True if updated
        """
        new_interval = max(MIN_POLL_INTERVAL, min(seconds, MAX_POLL_INTERVAL))

        if self._is_running:
            try:
                scheduler = self._get_scheduler()
                scheduler.reschedule_job(
                    self._job_id,
                    trigger=IntervalTrigger(seconds=new_interval)
                )
            except Exception as e:
                logger.error("Failed to reschedule job: %s", e)
                return False

        self.poll_interval = new_interval
        logger.info("Poll interval updated to %d seconds", new_interval)
        return True

    def test_discord(self) -> bool:
        """Test Discord webhook connection."""
        return self.discord.test_connection()

    def send_test_alert(self) -> bool:
        """Send a test alert to Discord."""
        from .analyzer import SentimentScore, SignalStrength

        test_result = SentimentResult(
            news_id="test_123",
            title="[TEST] This is a test alert from the Sentiment Bot",
            sentiment=SentimentScore.BULLISH,
            confidence=0.85,
            signal_strength=SignalStrength.MODERATE,
            assets=["BTC", "ETH"],
            reasoning="This is a test alert to verify the Discord integration is working correctly.",
            price_impact="up",
            timeframe="short_term"
        )

        return self.discord.send_sentiment_alert(test_result)


# Global bot instance for app integration
_bot_instance: Optional[SentimentBot] = None
_bot_lock = threading.Lock()


def get_sentiment_bot() -> Optional[SentimentBot]:
    """Get the global bot instance."""
    return _bot_instance


def create_sentiment_bot(
    database_url: str,
    anthropic_api_key: str,
    discord_webhook_url: str,
    cryptopanic_api_key: Optional[str] = None,
    poll_interval: int = DEFAULT_POLL_INTERVAL
) -> SentimentBot:
    """
    Create and store the global bot instance.

    Args:
        database_url: PostgreSQL connection string
        anthropic_api_key: Anthropic API key
        discord_webhook_url: Discord webhook URL
        cryptopanic_api_key: Optional CryptoPanic API key
        poll_interval: Seconds between polls

    Returns:
        SentimentBot instance
    """
    global _bot_instance

    with _bot_lock:
        if _bot_instance is not None:
            logger.warning("Bot instance already exists, returning existing")
            return _bot_instance

        _bot_instance = SentimentBot(
            database_url=database_url,
            anthropic_api_key=anthropic_api_key,
            discord_webhook_url=discord_webhook_url,
            cryptopanic_api_key=cryptopanic_api_key,
            poll_interval=poll_interval
        )

        return _bot_instance


def destroy_sentiment_bot() -> None:
    """Stop and destroy the global bot instance."""
    global _bot_instance

    with _bot_lock:
        if _bot_instance is not None:
            _bot_instance.stop(send_shutdown_message=False)
            _bot_instance = None
