import os
from dotenv import load_dotenv

load_dotenv()

# Your Hyperliquid wallet address (public address, no private key needed)
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")

# Hyperliquid API endpoint
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz/info"

# Database URL (PostgreSQL on Railway)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Data storage paths (fallback for local dev without DB)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TRADES_FILE = os.path.join(DATA_DIR, "trades.json")

# =============================================================================
# Sentiment Bot Configuration
# =============================================================================

# Anthropic API key for Claude sentiment analysis
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Discord webhook URL for alerts
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# CryptoPanic API key (optional, for additional news source)
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")

# Sentiment polling interval in seconds (default: 5 minutes)
SENTIMENT_POLL_INTERVAL = int(os.getenv("SENTIMENT_POLL_INTERVAL", "300"))

# Sentiment bot display name
SENTIMENT_BOT_NAME = os.getenv("SENTIMENT_BOT_NAME", "HL Sentiment Bot")
