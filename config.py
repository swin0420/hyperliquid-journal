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
