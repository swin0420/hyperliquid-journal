import os
from dotenv import load_dotenv

load_dotenv()

# Your Hyperliquid wallet address (public address, no private key needed)
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")

# Hyperliquid API endpoint
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz/info"

# Data storage paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TRADES_FILE = os.path.join(DATA_DIR, "trades.json")
