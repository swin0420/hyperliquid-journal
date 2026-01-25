"""SQLAlchemy models for sentiment signal history.

Stores news items, sentiment analysis results, and alert delivery status.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column, String, Float, Text, Boolean, DateTime, Integer,
    Index, ForeignKey, Enum as SQLEnum, create_engine
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session
from sqlalchemy.pool import QueuePool

from .analyzer import SentimentScore, SignalStrength

logger = logging.getLogger(__name__)

Base = declarative_base()

# Connection pool settings
POOL_SIZE = 3
POOL_MAX_OVERFLOW = 5
POOL_TIMEOUT = 30


class NewsRecord(Base):
    """Stored news item from aggregator."""
    __tablename__ = 'sentiment_news'

    id = Column(String(16), primary_key=True)  # URL hash
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    source = Column(String(50), nullable=False)  # cryptopanic, cryptonews
    source_name = Column(String(100))  # Publisher name
    published_at = Column(DateTime(timezone=True), nullable=False)
    currencies = Column(Text)  # JSON array as string
    raw_sentiment = Column(String(20))  # Source-provided sentiment
    fetched_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationship to analysis
    analysis = relationship("SignalRecord", back_populates="news", uselist=False)

    __table_args__ = (
        Index('idx_news_published', 'published_at'),
        Index('idx_news_source', 'source'),
    )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        import json
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "source_name": self.source_name,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "currencies": json.loads(self.currencies) if self.currencies else [],
            "raw_sentiment": self.raw_sentiment,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None
        }


class SignalRecord(Base):
    """Stored sentiment analysis result."""
    __tablename__ = 'sentiment_signals'

    id = Column(Integer, primary_key=True, autoincrement=True)
    news_id = Column(String(16), ForeignKey('sentiment_news.id'), nullable=False, unique=True)

    # Sentiment data
    sentiment = Column(String(20), nullable=False)  # very_bullish, bullish, etc.
    confidence = Column(Float, nullable=False)
    signal_strength = Column(String(20), nullable=False)  # strong, moderate, etc.
    price_impact = Column(String(20))  # up, down, neutral
    timeframe = Column(String(20))  # immediate, short_term, long_term
    reasoning = Column(Text)

    # Assets (JSON array as string)
    assets = Column(Text)

    # Metadata
    analyzed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_actionable = Column(Boolean, default=False)

    # Alert delivery
    alert_sent = Column(Boolean, default=False)
    alert_sent_at = Column(DateTime(timezone=True))
    alert_channel = Column(String(50))  # discord, telegram, etc.

    # Relationship to news
    news = relationship("NewsRecord", back_populates="analysis")

    __table_args__ = (
        Index('idx_signal_sentiment', 'sentiment'),
        Index('idx_signal_analyzed', 'analyzed_at'),
        Index('idx_signal_actionable', 'is_actionable'),
        Index('idx_signal_assets', 'assets'),
    )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        import json
        return {
            "id": self.id,
            "news_id": self.news_id,
            "sentiment": self.sentiment,
            "confidence": self.confidence,
            "signal_strength": self.signal_strength,
            "price_impact": self.price_impact,
            "timeframe": self.timeframe,
            "reasoning": self.reasoning,
            "assets": json.loads(self.assets) if self.assets else [],
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None,
            "is_actionable": self.is_actionable,
            "alert_sent": self.alert_sent,
            "alert_sent_at": self.alert_sent_at.isoformat() if self.alert_sent_at else None,
            "alert_channel": self.alert_channel,
            "news": self.news.to_dict() if self.news else None
        }


class BotStatus(Base):
    """Bot running status and configuration."""
    __tablename__ = 'sentiment_bot_status'

    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_address = Column(String(42), unique=True, nullable=False)  # For per-user bot instances
    is_enabled = Column(Boolean, default=False)
    poll_interval = Column(Integer, default=300)  # seconds
    last_poll_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    last_error_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_bot_wallet', 'wallet_address'),
        Index('idx_bot_enabled', 'is_enabled'),
    )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "wallet_address": self.wallet_address,
            "is_enabled": self.is_enabled,
            "poll_interval": self.poll_interval,
            "last_poll_at": self.last_poll_at.isoformat() if self.last_poll_at else None,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


# Database session management
_engine = None
_SessionLocal = None


def init_sentiment_db(database_url: str) -> bool:
    """
    Initialize the sentiment database tables.

    Args:
        database_url: PostgreSQL connection string

    Returns:
        True if successful
    """
    global _engine, _SessionLocal

    if not database_url:
        logger.error("No database URL provided for sentiment DB")
        return False

    try:
        # Handle Railway postgres:// URL
        db_url = database_url.replace("postgres://", "postgresql+psycopg://")
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://")

        _engine = create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=POOL_SIZE,
            max_overflow=POOL_MAX_OVERFLOW,
            pool_timeout=POOL_TIMEOUT,
            pool_pre_ping=True
        )

        Base.metadata.create_all(_engine)
        _SessionLocal = sessionmaker(bind=_engine)

        logger.info("Sentiment database initialized")
        return True

    except Exception as e:
        logger.error("Failed to initialize sentiment DB: %s", e)
        return False


def get_sentiment_session() -> Optional[Session]:
    """Get a database session."""
    if not _SessionLocal:
        return None
    return _SessionLocal()


class SignalRepository:
    """Repository for managing signal records."""

    def __init__(self, session: Session):
        """Initialize with a database session."""
        self.session = session

    def save_news(self, news_item) -> NewsRecord:
        """
        Save a news item to the database.

        Args:
            news_item: NewsItem from aggregator

        Returns:
            NewsRecord instance
        """
        import json

        existing = self.session.query(NewsRecord).filter(NewsRecord.id == news_item.id).first()
        if existing:
            return existing

        record = NewsRecord(
            id=news_item.id,
            title=news_item.title,
            url=news_item.url,
            source=news_item.source.value,
            source_name=news_item.source_name,
            published_at=news_item.published_at,
            currencies=json.dumps(news_item.currencies),
            raw_sentiment=news_item.raw_sentiment,
            fetched_at=news_item.fetched_at
        )

        self.session.add(record)
        self.session.flush()
        return record

    def save_signal(self, result, news_item=None) -> SignalRecord:
        """
        Save a sentiment signal to the database.

        Args:
            result: SentimentResult from analyzer
            news_item: Optional NewsItem (will be saved if provided)

        Returns:
            SignalRecord instance
        """
        import json

        # Save news item if provided
        if news_item:
            self.save_news(news_item)

        # Check for existing signal
        existing = self.session.query(SignalRecord).filter(
            SignalRecord.news_id == result.news_id
        ).first()

        if existing:
            # Update existing
            existing.sentiment = result.sentiment.value
            existing.confidence = result.confidence
            existing.signal_strength = result.signal_strength.value
            existing.price_impact = result.price_impact
            existing.timeframe = result.timeframe
            existing.reasoning = result.reasoning
            existing.assets = json.dumps(result.assets)
            existing.is_actionable = result.is_actionable
            return existing

        record = SignalRecord(
            news_id=result.news_id,
            sentiment=result.sentiment.value,
            confidence=result.confidence,
            signal_strength=result.signal_strength.value,
            price_impact=result.price_impact,
            timeframe=result.timeframe,
            reasoning=result.reasoning,
            assets=json.dumps(result.assets),
            analyzed_at=result.analyzed_at,
            is_actionable=result.is_actionable
        )

        self.session.add(record)
        self.session.flush()
        return record

    def mark_alert_sent(self, signal_id: int, channel: str = "discord") -> bool:
        """
        Mark a signal as having its alert sent.

        Args:
            signal_id: SignalRecord ID
            channel: Alert channel name

        Returns:
            True if updated
        """
        signal = self.session.query(SignalRecord).filter(SignalRecord.id == signal_id).first()
        if not signal:
            return False

        signal.alert_sent = True
        signal.alert_sent_at = datetime.now(timezone.utc)
        signal.alert_channel = channel
        return True

    def get_unsent_actionable_signals(self, limit: int = 50) -> list[SignalRecord]:
        """
        Get actionable signals that haven't been alerted yet.

        Args:
            limit: Maximum number to return

        Returns:
            List of SignalRecord objects
        """
        return (
            self.session.query(SignalRecord)
            .filter(SignalRecord.is_actionable == True)
            .filter(SignalRecord.alert_sent == False)
            .order_by(SignalRecord.analyzed_at.desc())
            .limit(limit)
            .all()
        )

    def get_recent_signals(
        self,
        limit: int = 50,
        sentiment: Optional[str] = None,
        asset: Optional[str] = None,
        actionable_only: bool = False
    ) -> list[SignalRecord]:
        """
        Get recent signals with optional filters.

        Args:
            limit: Maximum number to return
            sentiment: Filter by sentiment value
            asset: Filter by asset (searches in assets JSON)
            actionable_only: Only return actionable signals

        Returns:
            List of SignalRecord objects
        """
        query = self.session.query(SignalRecord)

        if sentiment:
            query = query.filter(SignalRecord.sentiment == sentiment)

        if asset:
            # Search in JSON array
            query = query.filter(SignalRecord.assets.contains(f'"{asset}"'))

        if actionable_only:
            query = query.filter(SignalRecord.is_actionable == True)

        return (
            query
            .order_by(SignalRecord.analyzed_at.desc())
            .limit(limit)
            .all()
        )

    def get_signal_stats(self, hours: int = 24) -> dict:
        """
        Get signal statistics for the last N hours.

        Args:
            hours: Number of hours to look back

        Returns:
            Dict with counts and breakdowns
        """
        from datetime import timedelta
        from sqlalchemy import func

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Count by sentiment
        sentiment_counts = (
            self.session.query(SignalRecord.sentiment, func.count(SignalRecord.id))
            .filter(SignalRecord.analyzed_at >= cutoff)
            .group_by(SignalRecord.sentiment)
            .all()
        )

        # Count actionable
        actionable_count = (
            self.session.query(func.count(SignalRecord.id))
            .filter(SignalRecord.analyzed_at >= cutoff)
            .filter(SignalRecord.is_actionable == True)
            .scalar()
        )

        # Total
        total = (
            self.session.query(func.count(SignalRecord.id))
            .filter(SignalRecord.analyzed_at >= cutoff)
            .scalar()
        )

        return {
            "total": total or 0,
            "actionable": actionable_count or 0,
            "by_sentiment": {s: c for s, c in sentiment_counts},
            "hours": hours
        }

    def news_exists(self, news_id: str) -> bool:
        """Check if a news item already exists."""
        return self.session.query(NewsRecord).filter(NewsRecord.id == news_id).first() is not None

    def cleanup_old_records(self, days: int = 30) -> int:
        """
        Delete records older than N days.

        Args:
            days: Age threshold

        Returns:
            Number of deleted records
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Delete signals first (foreign key)
        signals_deleted = (
            self.session.query(SignalRecord)
            .filter(SignalRecord.analyzed_at < cutoff)
            .delete(synchronize_session=False)
        )

        # Delete orphaned news
        news_deleted = (
            self.session.query(NewsRecord)
            .filter(NewsRecord.fetched_at < cutoff)
            .filter(~NewsRecord.id.in_(
                self.session.query(SignalRecord.news_id)
            ))
            .delete(synchronize_session=False)
        )

        logger.info("Cleaned up %d signals and %d news records older than %d days",
                    signals_deleted, news_deleted, days)

        return signals_deleted + news_deleted


class BotStatusRepository:
    """Repository for managing bot status."""

    def __init__(self, session: Session):
        """Initialize with a database session."""
        self.session = session

    def get_or_create(self, wallet_address: str) -> BotStatus:
        """Get or create bot status for a wallet."""
        wallet = wallet_address.lower()
        status = self.session.query(BotStatus).filter(BotStatus.wallet_address == wallet).first()

        if not status:
            status = BotStatus(wallet_address=wallet)
            self.session.add(status)
            self.session.flush()

        return status

    def enable(self, wallet_address: str, poll_interval: int = 300) -> BotStatus:
        """Enable the bot for a wallet."""
        status = self.get_or_create(wallet_address)
        status.is_enabled = True
        status.poll_interval = poll_interval
        status.last_error = None
        status.last_error_at = None
        return status

    def disable(self, wallet_address: str) -> BotStatus:
        """Disable the bot for a wallet."""
        status = self.get_or_create(wallet_address)
        status.is_enabled = False
        return status

    def record_poll(self, wallet_address: str) -> BotStatus:
        """Record a successful poll."""
        status = self.get_or_create(wallet_address)
        status.last_poll_at = datetime.now(timezone.utc)
        return status

    def record_error(self, wallet_address: str, error: str) -> BotStatus:
        """Record an error."""
        status = self.get_or_create(wallet_address)
        status.last_error = error
        status.last_error_at = datetime.now(timezone.utc)
        return status

    def get_enabled_bots(self) -> list[BotStatus]:
        """Get all enabled bot instances."""
        return self.session.query(BotStatus).filter(BotStatus.is_enabled == True).all()

    def is_enabled(self, wallet_address: str) -> bool:
        """Check if bot is enabled for a wallet."""
        wallet = wallet_address.lower()
        status = self.session.query(BotStatus).filter(BotStatus.wallet_address == wallet).first()
        return status.is_enabled if status else False
