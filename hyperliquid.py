import requests
from functools import lru_cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import HYPERLIQUID_API_URL
from constants import (
    Direction, Action, MarketType, ApiType, FillSide,
    API_DIRECTION_LONG, API_DIRECTION_OPEN, SPOT_ASSET_PREFIX
)

# Request configuration
REQUEST_TIMEOUT = 15  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 0.5  # exponential backoff factor

# Create a session with retry logic
def _get_http_session() -> requests.Session:
    """Create a requests session with retry and timeout configuration."""
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _api_request(payload: dict) -> dict | list:
    """Make an API request with timeout and retry handling."""
    session = _get_http_session()
    response = session.post(
        HYPERLIQUID_API_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


@lru_cache(maxsize=1)
def fetch_spot_meta() -> dict:
    """
    Fetch spot metadata to get token names for spot indices.
    Results are cached using lru_cache for thread-safety.

    Returns:
        Dict mapping spot index (e.g., "107") to token name (e.g., "HYPE/USDC")
    """
    data = _api_request({"type": ApiType.SPOT_META})
    spot_name_map = {}

    # Build mapping from spot index to name
    # Universe contains spot pairs with their names
    universe = data.get("universe", [])
    for spot in universe:
        index = spot.get("index")
        name = spot.get("name", "")
        if index is not None:
            # If name starts with @, try to build from tokens
            if name.startswith(SPOT_ASSET_PREFIX) or not name:
                tokens = spot.get("tokens", [])
                # tokens[0] is base, tokens[1] is quote (usually USDC = 0)
                # We need token metadata to resolve names
                token_list = data.get("tokens", [])
                if len(tokens) >= 2 and token_list:
                    base_idx = tokens[0]
                    quote_idx = tokens[1]
                    base_name = None
                    quote_name = None
                    for t in token_list:
                        if t.get("index") == base_idx:
                            base_name = t.get("name")
                        if t.get("index") == quote_idx:
                            quote_name = t.get("name")
                    if base_name:
                        name = f"{base_name}/USDC" if quote_idx == 0 else f"{base_name}/{quote_name or '?'}"
            spot_name_map[str(index)] = name

    return spot_name_map


def get_spot_name(asset: str) -> str:
    """
    Convert spot asset ID (@107) to readable name (HYPE/USDC).

    Args:
        asset: Asset string (e.g., "@107" or "BTC")

    Returns:
        Readable name
    """
    if not asset.startswith(SPOT_ASSET_PREFIX):
        return asset

    spot_index = asset[1:]  # Remove @ prefix
    spot_names = fetch_spot_meta()
    return spot_names.get(spot_index, asset)


def fetch_user_fills(wallet_address: str, aggregate_by_time: bool = True) -> list:
    """
    Fetch trading fills (trade history) for a wallet address from Hyperliquid.

    Args:
        wallet_address: The user's Hyperliquid wallet address
        aggregate_by_time: If True, combines partial fills from the same order

    Returns:
        List of fill objects with trade details
    """
    return _api_request({
        "type": ApiType.USER_FILLS,
        "user": wallet_address,
        "aggregateByTime": aggregate_by_time
    })


def parse_fill_to_trade(fill: dict) -> dict:
    """
    Convert a Hyperliquid fill object to our trade format.

    Args:
        fill: Raw fill object from Hyperliquid API

    Returns:
        Normalized trade object for our journal
    """
    asset = fill.get("coin", "")
    is_spot = asset.startswith(SPOT_ASSET_PREFIX)
    side = fill.get("side", "")  # B = buy, A = sell

    if is_spot:
        # Spot trading: Buy = open long, Sell = close long
        # Spot doesn't have shorting
        is_long = True
        is_open = side == FillSide.BUY
    else:
        # Perp trading: Use the dir field
        direction = fill.get("dir", "")
        is_long = API_DIRECTION_LONG in direction
        is_open = API_DIRECTION_OPEN in direction

    return {
        "id": str(fill.get("tid", fill.get("oid", ""))),
        "asset": asset,
        "direction": Direction.LONG if is_long else Direction.SHORT,
        "action": Action.OPEN if is_open else Action.CLOSE,
        "price": float(fill.get("px", 0)),
        "size": float(fill.get("sz", 0)),
        "pnl": float(fill.get("closedPnl", 0)),
        "fee": float(fill.get("fee", 0)),
        "timestamp": fill.get("time", 0),
        "hash": fill.get("hash", ""),
        "order_id": fill.get("oid"),
        "side": side,
        "start_position": float(fill.get("startPosition", 0)),
        "notes": ""  # User can add notes later
    }


def fetch_and_parse_trades(wallet_address: str) -> list:
    """
    Fetch fills from Hyperliquid and parse them into trade objects.

    Args:
        wallet_address: The user's wallet address

    Returns:
        List of parsed trade objects
    """
    fills = fetch_user_fills(wallet_address)
    return [parse_fill_to_trade(fill) for fill in fills]


def fetch_user_funding(wallet_address: str, start_time: int = 0) -> list:
    """
    Fetch funding payment history for a wallet address.

    Args:
        wallet_address: The user's Hyperliquid wallet address
        start_time: Start timestamp in milliseconds (0 = all time)

    Returns:
        List of funding payment objects
    """
    return _api_request({
        "type": ApiType.USER_FUNDING,
        "user": wallet_address,
        "startTime": start_time
    })


def parse_funding_events(funding_list: list) -> list:
    """
    Parse funding payments into a list of events with timestamps.

    Args:
        funding_list: Raw funding data from API

    Returns:
        List of funding event dicts
    """
    events = []
    for item in funding_list:
        delta = item.get("delta", {})
        events.append({
            "coin": delta.get("coin", ""),
            "usdc": float(delta.get("usdc", 0)),
            "timestamp": item.get("time", 0),
            "hash": item.get("hash", "")
        })
    return events


def fetch_funding_events(wallet_address: str) -> list:
    """
    Fetch funding payment events.

    Args:
        wallet_address: The user's wallet address

    Returns:
        List of funding events with timestamps
    """
    funding_data = fetch_user_funding(wallet_address)
    return parse_funding_events(funding_data)


def fetch_all_mids() -> dict:
    """
    Fetch current mid prices for all assets.

    Returns:
        Dict mapping asset name to mid price
    """
    return _api_request({"type": ApiType.ALL_MIDS})


def fetch_open_orders(wallet_address: str) -> list:
    """
    Fetch open orders for a wallet using frontendOpenOrders for full details.

    Args:
        wallet_address: The user's wallet address

    Returns:
        List of open orders with trigger prices
    """
    return _api_request({
        "type": ApiType.OPEN_ORDERS,
        "user": wallet_address
    })


def _fetch_clearinghouse_state(wallet_address: str) -> dict:
    """Fetch clearinghouse state for a wallet."""
    return _api_request({
        "type": ApiType.CLEARINGHOUSE_STATE,
        "user": wallet_address
    })


def fetch_open_positions(wallet_address: str) -> list:
    """
    Fetch current open positions from clearinghouse state.

    Args:
        wallet_address: The user's wallet address

    Returns:
        List of open position objects
    """
    # Parallel fetch: clearinghouse state, all mids, and open orders
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_fetch_clearinghouse_state, wallet_address): 'state',
            executor.submit(fetch_all_mids): 'mids',
            executor.submit(fetch_open_orders, wallet_address): 'orders'
        }

        results = {}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                # If any call fails, raise the error
                raise e

    data = results['state']
    all_mids = results['mids']
    open_orders = results['orders']

    # Group TP/SL orders by asset
    tp_sl_by_asset = {}
    for order in open_orders:
        asset = order.get("coin", "")
        order_type = order.get("orderType", "")
        trigger_px = order.get("triggerPx")
        is_tp_sl = order.get("isPositionTpsl", False)

        if not trigger_px or not is_tp_sl:
            continue

        if asset not in tp_sl_by_asset:
            tp_sl_by_asset[asset] = {"take_profit": None, "stop_loss": None}

        price = float(trigger_px)
        if "Take Profit" in order_type:
            tp_sl_by_asset[asset]["take_profit"] = price
        elif "Stop" in order_type:
            tp_sl_by_asset[asset]["stop_loss"] = price

    positions = []
    asset_positions = data.get("assetPositions", [])

    for item in asset_positions:
        pos = item.get("position", {})
        size = float(pos.get("szi", 0))

        # Skip if no position
        if size == 0:
            continue

        asset = pos.get("coin", "")
        entry_px = float(pos.get("entryPx", 0))
        unrealized_pnl = float(pos.get("unrealizedPnl", 0))
        leverage = pos.get("leverage", {})
        liq_px = pos.get("liquidationPx")
        is_long = size > 0

        # Get TP/SL for this asset
        tp_sl = tp_sl_by_asset.get(asset, {})

        # Get current price from allMids
        current_price = float(all_mids.get(asset, 0))

        positions.append({
            "asset": asset,
            "size": abs(size),
            "direction": Direction.LONG if is_long else Direction.SHORT,
            "entry_price": entry_px,
            "current_price": current_price,
            "unrealized_pnl": unrealized_pnl,
            "leverage": leverage.get("value", 1) if isinstance(leverage, dict) else leverage,
            "liquidation_price": float(liq_px) if liq_px else None,
            "margin_used": float(pos.get("marginUsed", 0)),
            "position_value": float(pos.get("positionValue", 0)),
            "take_profit": tp_sl.get("take_profit"),
            "stop_loss": tp_sl.get("stop_loss")
        })

    return positions
