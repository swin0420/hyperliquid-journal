"""Twitter/X aggregator using Nitter RSS feeds.

Fetches tweets from crypto influencer accounts via Nitter instances.
Nitter provides RSS feeds without requiring Twitter API access.
"""

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from html import unescape
import re

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Request configuration
REQUEST_TIMEOUT = 15
MAX_RETRIES = 2
RETRY_BACKOFF = 0.5

# Nitter instances (multiple for fallback - they go down often)
# Note: Nitter instances are notoriously unstable as Twitter/X blocks them
NITTER_INSTANCES = [
    "nitter.poast.org",
    "nitter.privacydev.net",
    "nitter.net",
    "nitter.cz",
    "nitter.unixfox.eu",
    "nitter.1d4.us",
    "nitter.kavin.rocks",
    "nitter.it",
    "nitter.domain.glass",
    "nitter.moomoo.me",
]

# Default accounts to track
DEFAULT_TWITTER_ACCOUNTS = [
    "cryptounfolded",
    "zoomerfied",
    "WatcherGuru",
]


def _get_http_session() -> requests.Session:
    """Create a requests session with retry logic."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "HLJournal/1.0 (Sentiment Bot; +https://hl-journal.xyz)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"
    })
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


def _clean_tweet_text(text: str) -> str:
    """Clean tweet text from HTML and normalize."""
    # Unescape HTML entities
    text = unescape(text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove multiple spaces/newlines
    text = re.sub(r'\s+', ' ', text)
    # Strip whitespace
    text = text.strip()
    return text


def _extract_twitter_url(nitter_url: str) -> str:
    """Convert Nitter URL to original Twitter URL."""
    # Nitter URLs look like: https://nitter.instance/user/status/123456
    # Convert to: https://twitter.com/user/status/123456
    for instance in NITTER_INSTANCES:
        if instance in nitter_url:
            return nitter_url.replace(f"https://{instance}", "https://twitter.com")
    # Fallback: try to extract path and rebuild
    match = re.search(r'/([^/]+)/status/(\d+)', nitter_url)
    if match:
        return f"https://twitter.com/{match.group(1)}/status/{match.group(2)}"
    return nitter_url


@dataclass
class TweetItem:
    """Raw tweet item before normalization."""
    id: str
    text: str
    url: str
    username: str
    published_at: datetime


class TwitterAggregator:
    """Aggregates tweets from crypto influencers via Nitter RSS."""

    def __init__(
        self,
        accounts: Optional[list[str]] = None,
        extract_assets_func: Optional[callable] = None
    ):
        """
        Initialize the Twitter aggregator.

        Args:
            accounts: List of Twitter usernames to track
            extract_assets_func: Function to extract asset symbols from text
        """
        self.accounts = accounts or DEFAULT_TWITTER_ACCOUNTS
        self._extract_assets = extract_assets_func
        self._session = _get_http_session()
        self._seen_urls: set[str] = set()
        self._working_instance: Optional[str] = None

    def _find_working_instance(self) -> Optional[str]:
        """Find a working Nitter instance."""
        # Try cached working instance first
        if self._working_instance:
            try:
                response = self._session.get(
                    f"https://{self._working_instance}/",
                    timeout=5
                )
                if response.status_code == 200:
                    return self._working_instance
            except Exception:
                pass

        # Try all instances
        for instance in NITTER_INSTANCES:
            try:
                response = self._session.get(
                    f"https://{instance}/",
                    timeout=5
                )
                if response.status_code == 200:
                    self._working_instance = instance
                    logger.info("Found working Nitter instance: %s", instance)
                    return instance
            except Exception as e:
                logger.debug("Nitter instance %s failed: %s", instance, e)
                continue

        logger.warning("No working Nitter instances found")
        return None

    def _fetch_user_rss(self, username: str, instance: str) -> list[TweetItem]:
        """
        Fetch RSS feed for a single user.

        Args:
            username: Twitter username
            instance: Nitter instance to use

        Returns:
            List of TweetItem objects
        """
        url = f"https://{instance}/{username}/rss"
        items = []

        try:
            response = self._session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            feed = feedparser.parse(response.content)

            if feed.bozo and not feed.entries:
                logger.warning("Failed to parse RSS for @%s: %s", username, feed.bozo_exception)
                return []

            for entry in feed.entries:
                try:
                    # Extract tweet text
                    text = entry.get("title", "") or entry.get("summary", "")
                    text = _clean_tweet_text(text)

                    if not text:
                        continue

                    # Get URL
                    link = entry.get("link", "")
                    twitter_url = _extract_twitter_url(link)

                    # Parse published time
                    published = entry.get("published_parsed")
                    if published:
                        published_at = datetime(*published[:6], tzinfo=timezone.utc)
                    else:
                        published_at = datetime.now(timezone.utc)

                    items.append(TweetItem(
                        id=_hash_url(twitter_url),
                        text=text[:500],  # Limit text length
                        url=twitter_url,
                        username=username,
                        published_at=published_at
                    ))

                except Exception as e:
                    logger.debug("Error parsing tweet entry: %s", e)
                    continue

        except requests.RequestException as e:
            logger.warning("Failed to fetch RSS for @%s from %s: %s", username, instance, e)

        return items

    def fetch_tweets(self, limit_per_account: int = 10) -> list[TweetItem]:
        """
        Fetch tweets from all tracked accounts.

        Args:
            limit_per_account: Maximum tweets per account

        Returns:
            List of TweetItem objects, deduplicated
        """
        instance = self._find_working_instance()
        if not instance:
            logger.error("No working Nitter instance available")
            return []

        all_tweets: list[TweetItem] = []

        for username in self.accounts:
            try:
                tweets = self._fetch_user_rss(username, instance)
                all_tweets.extend(tweets[:limit_per_account])
                # Small delay between requests to be nice
                time.sleep(0.3)
            except Exception as e:
                logger.warning("Error fetching tweets for @%s: %s", username, e)
                continue

        # Deduplicate by URL hash
        seen_ids: set[str] = set()
        unique_tweets: list[TweetItem] = []

        for tweet in all_tweets:
            if tweet.id not in seen_ids and tweet.id not in self._seen_urls:
                seen_ids.add(tweet.id)
                unique_tweets.append(tweet)

        # Update seen URLs
        self._seen_urls.update(seen_ids)

        # Sort by published time (newest first)
        unique_tweets.sort(key=lambda x: x.published_at, reverse=True)

        logger.info("Fetched %d unique tweets from %d accounts", len(unique_tweets), len(self.accounts))
        return unique_tweets

    def get_accounts(self) -> list[str]:
        """Get list of tracked accounts."""
        return self.accounts.copy()

    def add_account(self, username: str) -> None:
        """Add an account to track."""
        username = username.lstrip("@").lower()
        if username not in self.accounts:
            self.accounts.append(username)

    def remove_account(self, username: str) -> None:
        """Remove an account from tracking."""
        username = username.lstrip("@").lower()
        if username in self.accounts:
            self.accounts.remove(username)

    def clear_seen(self) -> None:
        """Clear the seen URLs cache."""
        self._seen_urls.clear()
