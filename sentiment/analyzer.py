"""Sentiment analyzer using Claude Haiku for crypto news.

Analyzes news headlines and returns structured sentiment signals.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .aggregator import NewsItem

logger = logging.getLogger(__name__)

# API configuration
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20250514"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 2
RETRY_BACKOFF = 0.5

# Rate limiting
MIN_REQUEST_INTERVAL = 0.1  # 100ms between requests
MAX_BATCH_SIZE = 10  # Max items per batch analysis


class SentimentScore(str, Enum):
    """Sentiment classification levels."""
    VERY_BULLISH = "very_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    VERY_BEARISH = "very_bearish"


class SignalStrength(str, Enum):
    """Trading signal strength."""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "none"


@dataclass
class SentimentResult:
    """Result of sentiment analysis for a news item."""
    news_id: str                     # Reference to NewsItem.id
    title: str                       # Original headline
    sentiment: SentimentScore        # Classified sentiment
    confidence: float                # 0.0 to 1.0
    signal_strength: SignalStrength  # Trading signal strength
    assets: list[str]                # Affected assets
    reasoning: str                   # Brief explanation
    price_impact: str                # "up", "down", "neutral"
    timeframe: str                   # "immediate", "short_term", "long_term"
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "news_id": self.news_id,
            "title": self.title,
            "sentiment": self.sentiment.value,
            "confidence": self.confidence,
            "signal_strength": self.signal_strength.value,
            "assets": self.assets,
            "reasoning": self.reasoning,
            "price_impact": self.price_impact,
            "timeframe": self.timeframe,
            "analyzed_at": self.analyzed_at.isoformat()
        }

    @property
    def is_actionable(self) -> bool:
        """Check if this signal is worth alerting on."""
        return (
            self.signal_strength in (SignalStrength.STRONG, SignalStrength.MODERATE)
            and self.confidence >= 0.6
            and self.sentiment != SentimentScore.NEUTRAL
        )


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


class SentimentAnalyzer:
    """Analyzes crypto news sentiment using Claude Haiku."""

    SYSTEM_PROMPT = """You are a crypto market sentiment analyzer. Analyze news headlines for their potential impact on cryptocurrency prices.

For each headline, provide:
1. sentiment: very_bullish, bullish, neutral, bearish, or very_bearish
2. confidence: 0.0 to 1.0 (how certain you are)
3. signal_strength: strong, moderate, weak, or none
4. price_impact: up, down, or neutral
5. timeframe: immediate (hours), short_term (days), or long_term (weeks+)
6. reasoning: Brief 1-sentence explanation

Consider:
- Regulatory news (SEC, legal) - usually high impact
- Exchange listings/delistings - moderate to high impact
- Partnership announcements - varies by partner significance
- Technical updates/upgrades - usually positive
- Security breaches/hacks - very negative
- Whale movements - short-term impact
- Macroeconomic factors - broad market impact

Be conservative with "strong" signals - only major events warrant them.
Return valid JSON only, no markdown."""

    def __init__(self, api_key: str):
        """
        Initialize the sentiment analyzer.

        Args:
            api_key: Anthropic API key
        """
        if not api_key:
            raise ValueError("Anthropic API key is required")

        self.api_key = api_key
        self._session = _get_http_session()
        self._last_request_time = 0.0

    def _rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _call_claude(self, prompt: str) -> Optional[str]:
        """
        Make a request to Claude API.

        Args:
            prompt: The user prompt

        Returns:
            Response text or None on error
        """
        self._rate_limit()

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }

        payload = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1024,
            "system": self.SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        try:
            response = self._session.post(
                ANTHROPIC_API_URL,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()

            # Extract text from response
            content = data.get("content", [])
            if content and content[0].get("type") == "text":
                return content[0].get("text", "")

            return None

        except requests.RequestException as e:
            logger.error("Claude API error: %s", e)
            return None

    def _parse_sentiment_response(self, response: str, news_item: NewsItem) -> Optional[SentimentResult]:
        """
        Parse Claude's JSON response into a SentimentResult.

        Args:
            response: Raw JSON string from Claude
            news_item: Original news item

        Returns:
            SentimentResult or None on parse error
        """
        try:
            # Clean up response (remove markdown if present)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            response = response.strip()

            data = json.loads(response)

            # Map string values to enums
            sentiment_map = {
                "very_bullish": SentimentScore.VERY_BULLISH,
                "bullish": SentimentScore.BULLISH,
                "neutral": SentimentScore.NEUTRAL,
                "bearish": SentimentScore.BEARISH,
                "very_bearish": SentimentScore.VERY_BEARISH
            }

            strength_map = {
                "strong": SignalStrength.STRONG,
                "moderate": SignalStrength.MODERATE,
                "weak": SignalStrength.WEAK,
                "none": SignalStrength.NONE
            }

            sentiment = sentiment_map.get(data.get("sentiment", "neutral"), SentimentScore.NEUTRAL)
            signal_strength = strength_map.get(data.get("signal_strength", "none"), SignalStrength.NONE)

            return SentimentResult(
                news_id=news_item.id,
                title=news_item.title,
                sentiment=sentiment,
                confidence=float(data.get("confidence", 0.5)),
                signal_strength=signal_strength,
                assets=news_item.currencies or data.get("assets", []),
                reasoning=data.get("reasoning", "No reasoning provided"),
                price_impact=data.get("price_impact", "neutral"),
                timeframe=data.get("timeframe", "short_term")
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse sentiment response: %s", e)
            return None

    def analyze_single(self, news_item: NewsItem) -> Optional[SentimentResult]:
        """
        Analyze a single news item.

        Args:
            news_item: NewsItem to analyze

        Returns:
            SentimentResult or None on error
        """
        prompt = f"""Analyze this crypto news headline:

Title: {news_item.title}
Source: {news_item.source_name}
Assets mentioned: {', '.join(news_item.currencies) if news_item.currencies else 'None specified'}
Published: {news_item.published_at.isoformat()}

Return JSON with: sentiment, confidence, signal_strength, price_impact, timeframe, reasoning"""

        response = self._call_claude(prompt)
        if not response:
            return None

        return self._parse_sentiment_response(response, news_item)

    def analyze_batch(self, news_items: list[NewsItem]) -> list[SentimentResult]:
        """
        Analyze multiple news items efficiently.

        Args:
            news_items: List of NewsItem objects

        Returns:
            List of SentimentResult objects (may be shorter than input on errors)
        """
        if not news_items:
            return []

        results: list[SentimentResult] = []

        # Process in batches
        for i in range(0, len(news_items), MAX_BATCH_SIZE):
            batch = news_items[i:i + MAX_BATCH_SIZE]

            # Build batch prompt
            headlines = []
            for idx, item in enumerate(batch):
                headlines.append(
                    f"{idx + 1}. [{', '.join(item.currencies) or 'CRYPTO'}] {item.title}"
                )

            prompt = f"""Analyze these {len(batch)} crypto news headlines for market sentiment.

Headlines:
{chr(10).join(headlines)}

Return a JSON array with one object per headline, each containing:
sentiment, confidence, signal_strength, price_impact, timeframe, reasoning

Example format:
[
  {{"sentiment": "bullish", "confidence": 0.8, "signal_strength": "moderate", "price_impact": "up", "timeframe": "short_term", "reasoning": "..."}},
  ...
]"""

            response = self._call_claude(prompt)
            if not response:
                # Fall back to individual analysis
                logger.warning("Batch analysis failed, falling back to individual")
                for item in batch:
                    result = self.analyze_single(item)
                    if result:
                        results.append(result)
                continue

            # Parse batch response
            try:
                response = response.strip()
                if response.startswith("```"):
                    response = response.split("```")[1]
                    if response.startswith("json"):
                        response = response[4:]
                response = response.strip()

                parsed = json.loads(response)

                if isinstance(parsed, list):
                    for idx, data in enumerate(parsed):
                        if idx < len(batch):
                            # Create result using batch item and parsed data
                            item = batch[idx]
                            sentiment_map = {
                                "very_bullish": SentimentScore.VERY_BULLISH,
                                "bullish": SentimentScore.BULLISH,
                                "neutral": SentimentScore.NEUTRAL,
                                "bearish": SentimentScore.BEARISH,
                                "very_bearish": SentimentScore.VERY_BEARISH
                            }
                            strength_map = {
                                "strong": SignalStrength.STRONG,
                                "moderate": SignalStrength.MODERATE,
                                "weak": SignalStrength.WEAK,
                                "none": SignalStrength.NONE
                            }

                            result = SentimentResult(
                                news_id=item.id,
                                title=item.title,
                                sentiment=sentiment_map.get(data.get("sentiment", "neutral"), SentimentScore.NEUTRAL),
                                confidence=float(data.get("confidence", 0.5)),
                                signal_strength=strength_map.get(data.get("signal_strength", "none"), SignalStrength.NONE),
                                assets=item.currencies,
                                reasoning=data.get("reasoning", ""),
                                price_impact=data.get("price_impact", "neutral"),
                                timeframe=data.get("timeframe", "short_term")
                            )
                            results.append(result)

            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Failed to parse batch response: %s", e)
                # Fall back to individual
                for item in batch:
                    result = self.analyze_single(item)
                    if result:
                        results.append(result)

        logger.info("Analyzed %d/%d news items", len(results), len(news_items))
        return results

    def get_actionable_signals(self, news_items: list[NewsItem]) -> list[SentimentResult]:
        """
        Analyze news and return only actionable signals.

        Args:
            news_items: List of NewsItem objects

        Returns:
            List of actionable SentimentResult objects
        """
        all_results = self.analyze_batch(news_items)
        actionable = [r for r in all_results if r.is_actionable]

        logger.info("Found %d actionable signals from %d items", len(actionable), len(news_items))
        return actionable


def create_alert_message(result: SentimentResult) -> str:
    """
    Create a formatted alert message for a sentiment result.

    Args:
        result: SentimentResult to format

    Returns:
        Formatted string for alerts
    """
    # Emoji mapping
    sentiment_emoji = {
        SentimentScore.VERY_BULLISH: "🚀🟢",
        SentimentScore.BULLISH: "🟢",
        SentimentScore.NEUTRAL: "⚪",
        SentimentScore.BEARISH: "🔴",
        SentimentScore.VERY_BEARISH: "🔴💀"
    }

    strength_label = {
        SignalStrength.STRONG: "⚡ STRONG",
        SignalStrength.MODERATE: "📊 MODERATE",
        SignalStrength.WEAK: "📉 WEAK",
        SignalStrength.NONE: "—"
    }

    emoji = sentiment_emoji.get(result.sentiment, "⚪")
    strength = strength_label.get(result.signal_strength, "—")
    assets_str = ", ".join(result.assets) if result.assets else "CRYPTO"
    confidence_pct = int(result.confidence * 100)

    message = f"""{emoji} **{result.sentiment.value.upper().replace('_', ' ')}** | {strength}

**Assets:** {assets_str}
**Confidence:** {confidence_pct}%
**Impact:** {result.price_impact.upper()} ({result.timeframe.replace('_', ' ')})

📰 {result.title}

💡 {result.reasoning}"""

    return message
