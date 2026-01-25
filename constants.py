"""Constants used throughout the application."""

from enum import Enum


# Trade directions
class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


# Trade actions
class Action(str, Enum):
    OPEN = "open"
    CLOSE = "close"


# Market types
class MarketType(str, Enum):
    SPOT = "spot"
    PERP = "perp"


# Hyperliquid API request types
class ApiType(str, Enum):
    SPOT_META = "spotMeta"
    USER_FILLS = "userFills"
    USER_FUNDING = "userFunding"
    ALL_MIDS = "allMids"
    OPEN_ORDERS = "frontendOpenOrders"
    CLEARINGHOUSE_STATE = "clearinghouseState"


# Hyperliquid API fill sides
class FillSide(str, Enum):
    BUY = "B"
    SELL = "A"


# API direction indicators (used in parsing)
API_DIRECTION_LONG = "Long"
API_DIRECTION_OPEN = "Open"

# Asset prefixes
SPOT_ASSET_PREFIX = "@"

# Round trip ID prefix
ROUND_TRIP_PREFIX = "rt_"


# Error messages
class ErrorMsg:
    WALLET_REQUIRED = "Wallet address required"
    WALLET_NOT_PROVIDED = "No wallet address provided"
    WALLET_INVALID = "Invalid wallet address format"
    NOTES_REQUIRED = "Notes field required"
    TRADE_NOT_FOUND = "Trade not found"
