"""News aggregator for crypto sentiment analysis.

Fetches news from multiple sources:
- CryptoPanic API (requires API key)
- Free Crypto News API (no key required)
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from enum import Enum

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Request configuration
REQUEST_TIMEOUT = 10
MAX_RETRIES = 2
RETRY_BACKOFF = 0.3


class NewsSource(str, Enum):
    """News source identifiers."""
    CRYPTOPANIC = "cryptopanic"
    CRYPTONEWS = "cryptonews"


@dataclass
class NewsItem:
    """Normalized news item from any source."""
    id: str                          # Unique hash of URL
    title: str                       # Headline
    url: str                         # Original article URL
    source: NewsSource               # Which API it came from
    source_name: str                 # Publisher name (e.g., "CoinDesk")
    published_at: datetime           # Publication timestamp
    currencies: list[str] = field(default_factory=list)  # Related assets ["BTC", "ETH"]
    raw_sentiment: Optional[str] = None  # Source-provided sentiment if any
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source.value,
            "source_name": self.source_name,
            "published_at": self.published_at.isoformat(),
            "currencies": self.currencies,
            "raw_sentiment": self.raw_sentiment,
            "fetched_at": self.fetched_at.isoformat()
        }


def _get_http_session() -> requests.Session:
    """Create a requests session with retry logic."""
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _hash_url(url: str) -> str:
    """Generate a unique ID from URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


class NewsAggregator:
    """Aggregates news from multiple crypto news sources."""

    # Hyperliquid-listed assets (major ones for filtering)
    # This can be expanded or fetched dynamically
    HYPERLIQUID_ASSETS = {
        "BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "AVAX", "DOT", "MATIC",
        "LINK", "UNI", "ATOM", "LTC", "BCH", "NEAR", "APT", "ARB", "OP",
        "SUI", "SEI", "TIA", "INJ", "FTM", "RUNE", "STX", "IMX", "MINA",
        "BLUR", "GMX", "AAVE", "MKR", "CRV", "LDO", "SNX", "COMP", "SUSHI",
        "YFI", "1INCH", "BAL", "PERP", "DYDX", "JTO", "JUP", "WIF", "BONK",
        "PEPE", "SHIB", "FLOKI", "MEME", "ORDI", "HYPE", "PURR", "JEFF"
    }

    # Common aliases for assets
    ASSET_ALIASES = {
        "BITCOIN": "BTC",
        "ETHEREUM": "ETH",
        "SOLANA": "SOL",
        "DOGECOIN": "DOGE",
        "RIPPLE": "XRP",
        "CARDANO": "ADA",
        "AVALANCHE": "AVAX",
        "POLKADOT": "DOT",
        "POLYGON": "MATIC",
        "CHAINLINK": "LINK",
        "UNISWAP": "UNI",
        "COSMOS": "ATOM",
        "LITECOIN": "LTC",
        "ARBITRUM": "ARB",
        "OPTIMISM": "OP",
    }

    def __init__(
        self,
        cryptopanic_api_key: Optional[str] = None,
        filter_by_assets: bool = True
    ):
        """
        Initialize the news aggregator.

        Args:
            cryptopanic_api_key: API key for CryptoPanic (optional)
            filter_by_assets: If True, only return news for Hyperliquid assets
        """
        self.cryptopanic_api_key = cryptopanic_api_key
        self.filter_by_assets = filter_by_assets
        self._session = _get_http_session()
        self._seen_urls: set[str] = set()

    def _normalize_asset(self, asset: str) -> Optional[str]:
        """Normalize asset name to ticker symbol."""
        asset_upper = asset.upper().strip()

        # Direct match
        if asset_upper in self.HYPERLIQUID_ASSETS:
            return asset_upper

        # Alias match
        if asset_upper in self.ASSET_ALIASES:
            return self.ASSET_ALIASES[asset_upper]

        return None

    def _extract_assets_from_text(self, text: str) -> list[str]:
        """Extract mentioned assets from title/text."""
        assets = set()
        text_upper = text.upper()

        # Check for direct ticker mentions
        for asset in self.HYPERLIQUID_ASSETS:
            # Look for word boundaries to avoid false positives
            if f" {asset} " in f" {text_upper} " or f"${asset}" in text_upper:
                assets.add(asset)

        # Check for full name mentions
        for name, ticker in self.ASSET_ALIASES.items():
            if name in text_upper:
                assets.add(ticker)

        return list(assets)

    def fetch_cryptopanic(self, limit: int = 50) -> list[NewsItem]:
        """
        Fetch news from CryptoPanic API.

        Args:
            limit: Maximum number of items to fetch

        Returns:
            List of NewsItem objects
        """
        if not self.cryptopanic_api_key:
            logger.debug("CryptoPanic API key not configured, skipping")
            return []

        url = "https://cryptopanic.com/api/v1/posts/"
        params = {
            "auth_token": self.cryptopanic_api_key,
            "kind": "news",
            "filter": "hot",  # hot, rising, bullish, bearish, important, saved, lol
            "public": "true"
        }

        try:
            response = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error("CryptoPanic API error: %s", e)
            return []

        items = []
        for post in data.get("results", [])[:limit]:
            try:
                # Extract currencies from the API response
                currencies = []
                for currency in post.get("currencies", []):
                    code = currency.get("code", "").upper()
                    if code in self.HYPERLIQUID_ASSETS:
                        currencies.append(code)

                # Also extract from title
                title = post.get("title", "")
                title_assets = self._extract_assets_from_text(title)
                currencies = list(set(currencies + title_assets))

                # Skip if no relevant assets and filtering is enabled
                if self.filter_by_assets and not currencies:
                    continue

                # Parse timestamp
                published_str = post.get("published_at", "")
                try:
                    published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                except ValueError:
                    published_at = datetime.now(timezone.utc)

                # Get source sentiment votes
                votes = post.get("votes", {})
                if votes.get("positive", 0) > votes.get("negative", 0):
                    raw_sentiment = "positive"
                elif votes.get("negative", 0) > votes.get("positive", 0):
                    raw_sentiment = "negative"
                else:
                    raw_sentiment = "neutral"

                news_url = post.get("url", "")
                item = NewsItem(
                    id=_hash_url(news_url),
                    title=title,
                    url=news_url,
                    source=NewsSource.CRYPTOPANIC,
                    source_name=post.get("source", {}).get("title", "Unknown"),
                    published_at=published_at,
                    currencies=currencies,
                    raw_sentiment=raw_sentiment
                )
                items.append(item)

            except Exception as e:
                logger.warning("Error parsing CryptoPanic item: %s", e)
                continue

        logger.info("Fetched %d items from CryptoPanic", len(items))
        return items

    def fetch_cryptonews(self, limit: int = 50) -> list[NewsItem]:
        """
        Fetch news from Free Crypto News API.

        Args:
            limit: Maximum number of items to fetch

        Returns:
            List of NewsItem objects
        """
        # Free Crypto News API endpoint
        url = "https://min-api.cryptocompare.com/data/v2/news/"
        params = {
            "lang": "EN",
            "sortOrder": "latest"
        }

        try:
            response = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error("CryptoNews API error: %s", e)
            return []

        if data.get("Response") == "Error":
            logger.error("CryptoNews API returned error: %s", data.get("Message"))
            return []

        items = []
        for article in data.get("Data", [])[:limit]:
            try:
                title = article.get("title", "")

                # Extract assets from categories and title
                currencies = []
                categories = article.get("categories", "").upper().split("|")
                for cat in categories:
                    cat = cat.strip()
                    if cat in self.HYPERLIQUID_ASSETS:
                        currencies.append(cat)

                # Also extract from title
                title_assets = self._extract_assets_from_text(title)
                currencies = list(set(currencies + title_assets))

                # Skip if no relevant assets and filtering is enabled
                if self.filter_by_assets and not currencies:
                    continue

                # Parse timestamp (Unix timestamp)
                published_ts = article.get("published_on", 0)
                published_at = datetime.fromtimestamp(published_ts, tz=timezone.utc)

                news_url = article.get("url", "")
                item = NewsItem(
                    id=_hash_url(news_url),
                    title=title,
                    url=news_url,
                    source=NewsSource.CRYPTONEWS,
                    source_name=article.get("source_info", {}).get("name", article.get("source", "Unknown")),
                    published_at=published_at,
                    currencies=currencies,
                    raw_sentiment=None  # This API doesn't provide sentiment
                )
                items.append(item)

            except Exception as e:
                logger.warning("Error parsing CryptoNews item: %s", e)
                continue

        logger.info("Fetched %d items from CryptoNews", len(items))
        return items

    def fetch_all(self, limit_per_source: int = 30) -> list[NewsItem]:
        """
        Fetch and aggregate news from all sources.

        Args:
            limit_per_source: Maximum items per source

        Returns:
            Deduplicated list of NewsItem objects, sorted by published_at desc
        """
        all_items: list[NewsItem] = []

        # Fetch from all sources
        all_items.extend(self.fetch_cryptopanic(limit=limit_per_source))
        all_items.extend(self.fetch_cryptonews(limit=limit_per_source))

        # Deduplicate by URL hash
        seen_ids: set[str] = set()
        unique_items: list[NewsItem] = []

        for item in all_items:
            if item.id not in seen_ids and item.id not in self._seen_urls:
                seen_ids.add(item.id)
                unique_items.append(item)

        # Update seen URLs for future deduplication
        self._seen_urls.update(seen_ids)

        # Sort by published time (newest first)
        unique_items.sort(key=lambda x: x.published_at, reverse=True)

        logger.info("Aggregated %d unique news items", len(unique_items))
        return unique_items

    def get_new_items(self, limit_per_source: int = 30) -> list[NewsItem]:
        """
        Fetch only news items not seen before.

        Args:
            limit_per_source: Maximum items per source

        Returns:
            List of new NewsItem objects only
        """
        return self.fetch_all(limit_per_source=limit_per_source)

    def clear_seen(self) -> None:
        """Clear the seen URLs cache."""
        self._seen_urls.clear()
        logger.info("Cleared seen URLs cache")

    def add_asset(self, asset: str) -> bool:
        """
        Add a new asset to track.

        Args:
            asset: Asset ticker (e.g., "BTC")

        Returns:
            True if added, False if already exists
        """
        asset_upper = asset.upper()
        if asset_upper in self.HYPERLIQUID_ASSETS:
            return False
        self.HYPERLIQUID_ASSETS.add(asset_upper)
        return True

    def remove_asset(self, asset: str) -> bool:
        """
        Remove an asset from tracking.

        Args:
            asset: Asset ticker

        Returns:
            True if removed, False if not found
        """
        asset_upper = asset.upper()
        if asset_upper not in self.HYPERLIQUID_ASSETS:
            return False
        self.HYPERLIQUID_ASSETS.discard(asset_upper)
        return True
