"""Discord webhook integration for sentiment alerts.

Sends formatted alerts to Discord channels via webhooks.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .analyzer import SentimentResult, SentimentScore, SignalStrength

logger = logging.getLogger(__name__)

# Discord API configuration
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_BACKOFF = 1.0

# Rate limiting (Discord allows 30 requests per minute per webhook)
MIN_REQUEST_INTERVAL = 2.0  # 2 seconds between messages
MAX_EMBEDS_PER_MESSAGE = 10

# Colors for embeds (decimal format)
COLORS = {
    SentimentScore.VERY_BULLISH: 0x00FF00,  # Bright green
    SentimentScore.BULLISH: 0x90EE90,        # Light green
    SentimentScore.NEUTRAL: 0x808080,        # Gray
    SentimentScore.BEARISH: 0xFFA500,        # Orange
    SentimentScore.VERY_BEARISH: 0xFF0000,   # Red
}

# Emojis
SENTIMENT_EMOJI = {
    SentimentScore.VERY_BULLISH: "🚀",
    SentimentScore.BULLISH: "📈",
    SentimentScore.NEUTRAL: "➖",
    SentimentScore.BEARISH: "📉",
    SentimentScore.VERY_BEARISH: "💀",
}

STRENGTH_EMOJI = {
    SignalStrength.STRONG: "⚡",
    SignalStrength.MODERATE: "📊",
    SignalStrength.WEAK: "💤",
    SignalStrength.NONE: "—",
}


def _get_http_session() -> requests.Session:
    """Create a requests session with retry logic."""
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session


@dataclass
class DiscordEmbed:
    """Discord embed structure."""
    title: str
    description: str
    color: int
    fields: list[dict]
    footer: Optional[str] = None
    timestamp: Optional[str] = None
    url: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to Discord API format."""
        embed = {
            "title": self.title[:256],  # Discord limit
            "description": self.description[:4096],  # Discord limit
            "color": self.color,
            "fields": self.fields[:25]  # Discord limit
        }

        if self.footer:
            embed["footer"] = {"text": self.footer[:2048]}

        if self.timestamp:
            embed["timestamp"] = self.timestamp

        if self.url:
            embed["url"] = self.url

        return embed


class DiscordWebhook:
    """Discord webhook client for sending alerts."""

    def __init__(self, webhook_url: str, bot_name: str = "Sentiment Bot", avatar_url: Optional[str] = None):
        """
        Initialize Discord webhook client.

        Args:
            webhook_url: Discord webhook URL
            bot_name: Display name for the bot
            avatar_url: Optional avatar image URL
        """
        if not webhook_url:
            raise ValueError("Discord webhook URL is required")

        if not webhook_url.startswith("https://discord.com/api/webhooks/"):
            raise ValueError("Invalid Discord webhook URL format")

        self.webhook_url = webhook_url
        self.bot_name = bot_name
        self.avatar_url = avatar_url
        self._session = _get_http_session()
        self._last_request_time = 0.0

    def _rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _send_request(self, payload: dict) -> bool:
        """
        Send a request to the Discord webhook.

        Args:
            payload: JSON payload

        Returns:
            True if successful, False otherwise
        """
        self._rate_limit()

        try:
            response = self._session.post(
                self.webhook_url,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

            # Handle rate limiting
            if response.status_code == 429:
                retry_after = response.json().get("retry_after", 5)
                logger.warning("Discord rate limited, waiting %s seconds", retry_after)
                time.sleep(retry_after)
                # Retry once
                response = self._session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=REQUEST_TIMEOUT
                )

            response.raise_for_status()
            return True

        except requests.RequestException as e:
            logger.error("Discord webhook error: %s", e)
            return False

    def send_message(self, content: str) -> bool:
        """
        Send a simple text message.

        Args:
            content: Message text (max 2000 chars)

        Returns:
            True if successful
        """
        payload = {
            "username": self.bot_name,
            "content": content[:2000]
        }

        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url

        return self._send_request(payload)

    def send_embed(self, embed: DiscordEmbed) -> bool:
        """
        Send a single embed.

        Args:
            embed: DiscordEmbed object

        Returns:
            True if successful
        """
        payload = {
            "username": self.bot_name,
            "embeds": [embed.to_dict()]
        }

        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url

        return self._send_request(payload)

    def send_embeds(self, embeds: list[DiscordEmbed]) -> bool:
        """
        Send multiple embeds in one message.

        Args:
            embeds: List of DiscordEmbed objects (max 10)

        Returns:
            True if successful
        """
        if not embeds:
            return True

        # Discord allows max 10 embeds per message
        embeds = embeds[:MAX_EMBEDS_PER_MESSAGE]

        payload = {
            "username": self.bot_name,
            "embeds": [e.to_dict() for e in embeds]
        }

        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url

        return self._send_request(payload)

    def send_sentiment_alert(self, result: SentimentResult, news_url: Optional[str] = None) -> bool:
        """
        Send a formatted sentiment alert.

        Args:
            result: SentimentResult to send
            news_url: Optional URL to the news article

        Returns:
            True if successful
        """
        # Build embed
        sentiment_emoji = SENTIMENT_EMOJI.get(result.sentiment, "❓")
        strength_emoji = STRENGTH_EMOJI.get(result.signal_strength, "")
        color = COLORS.get(result.sentiment, 0x808080)

        # Title with sentiment
        title = f"{sentiment_emoji} {result.sentiment.value.upper().replace('_', ' ')}"
        if result.signal_strength in (SignalStrength.STRONG, SignalStrength.MODERATE):
            title += f" {strength_emoji}"

        # Description
        description = f"**{result.title}**"

        # Fields
        fields = [
            {
                "name": "Assets",
                "value": ", ".join(result.assets) if result.assets else "General Crypto",
                "inline": True
            },
            {
                "name": "Confidence",
                "value": f"{int(result.confidence * 100)}%",
                "inline": True
            },
            {
                "name": "Signal",
                "value": f"{result.signal_strength.value.title()}",
                "inline": True
            },
            {
                "name": "Price Impact",
                "value": f"{result.price_impact.upper()} ({result.timeframe.replace('_', ' ')})",
                "inline": True
            },
            {
                "name": "Analysis",
                "value": result.reasoning[:1024] if result.reasoning else "No analysis provided",
                "inline": False
            }
        ]

        embed = DiscordEmbed(
            title=title,
            description=description,
            color=color,
            fields=fields,
            footer="Hyperliquid Sentiment Bot",
            timestamp=result.analyzed_at.isoformat(),
            url=news_url
        )

        return self.send_embed(embed)

    def send_batch_alerts(self, results: list[SentimentResult], news_urls: Optional[dict[str, str]] = None) -> int:
        """
        Send multiple sentiment alerts efficiently.

        Args:
            results: List of SentimentResult objects
            news_urls: Optional dict mapping news_id to URL

        Returns:
            Number of successfully sent alerts
        """
        if not results:
            return 0

        news_urls = news_urls or {}
        sent_count = 0

        # Group by batches of 10 (Discord limit)
        for i in range(0, len(results), MAX_EMBEDS_PER_MESSAGE):
            batch = results[i:i + MAX_EMBEDS_PER_MESSAGE]
            embeds = []

            for result in batch:
                sentiment_emoji = SENTIMENT_EMOJI.get(result.sentiment, "❓")
                strength_emoji = STRENGTH_EMOJI.get(result.signal_strength, "")
                color = COLORS.get(result.sentiment, 0x808080)

                title = f"{sentiment_emoji} {result.sentiment.value.upper().replace('_', ' ')}"
                if result.signal_strength in (SignalStrength.STRONG, SignalStrength.MODERATE):
                    title += f" {strength_emoji}"

                # Compact fields for batch
                fields = [
                    {
                        "name": "Assets",
                        "value": ", ".join(result.assets) if result.assets else "Crypto",
                        "inline": True
                    },
                    {
                        "name": "Confidence",
                        "value": f"{int(result.confidence * 100)}%",
                        "inline": True
                    },
                    {
                        "name": "Impact",
                        "value": f"{result.price_impact.upper()}",
                        "inline": True
                    }
                ]

                embed = DiscordEmbed(
                    title=title,
                    description=f"**{result.title[:200]}**\n\n{result.reasoning[:500]}",
                    color=color,
                    fields=fields,
                    url=news_urls.get(result.news_id)
                )
                embeds.append(embed)

            if self.send_embeds(embeds):
                sent_count += len(embeds)

        logger.info("Sent %d/%d alerts to Discord", sent_count, len(results))
        return sent_count

    def send_summary(
        self,
        bullish_count: int,
        bearish_count: int,
        neutral_count: int,
        top_assets: list[tuple[str, int]],
        period: str = "Last 5 minutes"
    ) -> bool:
        """
        Send a summary of recent sentiment.

        Args:
            bullish_count: Number of bullish signals
            bearish_count: Number of bearish signals
            neutral_count: Number of neutral signals
            top_assets: List of (asset, mention_count) tuples
            period: Time period description

        Returns:
            True if successful
        """
        total = bullish_count + bearish_count + neutral_count
        if total == 0:
            return True  # Nothing to report

        # Determine overall sentiment
        if bullish_count > bearish_count * 1.5:
            color = COLORS[SentimentScore.BULLISH]
            overall = "📈 Bullish"
        elif bearish_count > bullish_count * 1.5:
            color = COLORS[SentimentScore.BEARISH]
            overall = "📉 Bearish"
        else:
            color = COLORS[SentimentScore.NEUTRAL]
            overall = "➖ Mixed"

        # Build description
        description = f"**Overall Sentiment:** {overall}\n\n"
        description += f"🟢 Bullish: {bullish_count}\n"
        description += f"🔴 Bearish: {bearish_count}\n"
        description += f"⚪ Neutral: {neutral_count}\n"

        # Top assets
        if top_assets:
            assets_str = ", ".join([f"**{asset}** ({count})" for asset, count in top_assets[:5]])
            description += f"\n**Trending Assets:** {assets_str}"

        embed = DiscordEmbed(
            title=f"📊 Sentiment Summary | {period}",
            description=description,
            color=color,
            fields=[],
            footer="Hyperliquid Sentiment Bot",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        return self.send_embed(embed)

    def send_error(self, error_message: str) -> bool:
        """
        Send an error notification.

        Args:
            error_message: Error description

        Returns:
            True if successful
        """
        embed = DiscordEmbed(
            title="⚠️ Sentiment Bot Error",
            description=f"```\n{error_message[:3000]}\n```",
            color=0xFF6B6B,  # Red-ish
            fields=[],
            footer="Check logs for details",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        return self.send_embed(embed)

    def send_startup_message(self) -> bool:
        """Send a message indicating the bot has started."""
        embed = DiscordEmbed(
            title="🤖 Sentiment Bot Online",
            description="Monitoring crypto news for trading signals...",
            color=0x00BFFF,  # Deep sky blue
            fields=[
                {
                    "name": "Features",
                    "value": "• Real-time news monitoring\n• AI sentiment analysis\n• Actionable trading signals",
                    "inline": False
                }
            ],
            footer="Hyperliquid Trade Journal",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        return self.send_embed(embed)

    def send_shutdown_message(self) -> bool:
        """Send a message indicating the bot is stopping."""
        embed = DiscordEmbed(
            title="🔴 Sentiment Bot Offline",
            description="Bot has been stopped. No more alerts will be sent.",
            color=0x808080,  # Gray
            fields=[],
            footer="Hyperliquid Trade Journal",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        return self.send_embed(embed)

    def test_connection(self) -> bool:
        """
        Test the webhook connection.

        Returns:
            True if connection is working
        """
        try:
            return self.send_message("🔧 Webhook test successful!")
        except Exception as e:
            logger.error("Webhook test failed: %s", e)
            return False
