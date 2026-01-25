"""Sentiment analysis module for crypto news alerts."""

from .aggregator import NewsAggregator, NewsItem, NewsSource
from .analyzer import (
    SentimentAnalyzer,
    SentimentResult,
    SentimentScore,
    SignalStrength,
    create_alert_message
)
from .discord_bot import DiscordWebhook, DiscordEmbed
from .models import (
    NewsRecord,
    SignalRecord,
    BotStatus,
    SignalRepository,
    BotStatusRepository,
    init_sentiment_db,
    get_sentiment_session
)
from .signal_scheduler import (
    SentimentBot,
    get_sentiment_bot,
    create_sentiment_bot,
    destroy_sentiment_bot
)

__all__ = [
    # Aggregator
    "NewsAggregator",
    "NewsItem",
    "NewsSource",
    # Analyzer
    "SentimentAnalyzer",
    "SentimentResult",
    "SentimentScore",
    "SignalStrength",
    "create_alert_message",
    # Discord
    "DiscordWebhook",
    "DiscordEmbed",
    # Models
    "NewsRecord",
    "SignalRecord",
    "BotStatus",
    "SignalRepository",
    "BotStatusRepository",
    "init_sentiment_db",
    "get_sentiment_session",
    # Scheduler
    "SentimentBot",
    "get_sentiment_bot",
    "create_sentiment_bot",
    "destroy_sentiment_bot",
]
