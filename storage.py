import json
import os
from config import TRADES_FILE, DATA_DIR
from hyperliquid import get_spot_name


def ensure_data_dir():
    """Ensure the data directory exists."""
    os.makedirs(DATA_DIR, exist_ok=True)


def load_trades_data() -> dict:
    """Load the full trades data including metadata."""
    ensure_data_dir()
    if not os.path.exists(TRADES_FILE):
        return {"wallet": None, "trades": {}}

    with open(TRADES_FILE, "r") as f:
        data = json.load(f)
        # Handle old format (dict of trades without wrapper)
        if "trades" not in data:
            return {"wallet": None, "trades": data}
        return data


def load_trades() -> dict:
    """
    Load trades from JSON file.

    Returns:
        Dict mapping trade IDs to trade objects
    """
    return load_trades_data().get("trades", {})


def get_stored_wallet() -> str:
    """Get the wallet address stored with the trades."""
    return load_trades_data().get("wallet")


def save_trades(trades: dict, wallet: str = None):
    """
    Save trades to JSON file.

    Args:
        trades: Dict mapping trade IDs to trade objects
        wallet: Optional wallet address to store with trades
    """
    ensure_data_dir()
    data = load_trades_data()
    data["trades"] = trades
    if wallet:
        data["wallet"] = wallet
    with open(TRADES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def merge_trades(existing: dict, new_trades: list) -> dict:
    """
    Merge new trades with existing trades, preserving notes.

    Args:
        existing: Existing trades dict
        new_trades: List of new trade objects from API

    Returns:
        Merged trades dict
    """
    for trade in new_trades:
        trade_id = trade["id"]
        if trade_id in existing:
            # Preserve existing notes
            trade["notes"] = existing[trade_id].get("notes", "")
        existing[trade_id] = trade
    return existing


def update_trade_notes(trade_id: str, notes: str) -> bool:
    """
    Update notes for a specific trade.

    Args:
        trade_id: The trade ID to update
        notes: The new notes content

    Returns:
        True if successful, False if trade not found
    """
    trades = load_trades()
    if trade_id not in trades:
        return False

    trades[trade_id]["notes"] = notes
    save_trades(trades)
    return True


def get_trades_sorted(descending: bool = True) -> list:
    """
    Get all trades sorted by timestamp.

    Args:
        descending: If True, newest first (default)

    Returns:
        List of trades sorted by timestamp
    """
    trades = load_trades()
    trade_list = list(trades.values())
    trade_list.sort(key=lambda x: x.get("timestamp", 0), reverse=descending)
    return trade_list


def get_round_trips() -> list:
    """
    Group individual fills into round-trip trades (open -> close cycles).

    Returns:
        List of round-trip trade objects with entry/exit prices and P&L
    """
    trades = load_trades()
    if not trades:
        return []

    # Sort fills by timestamp (oldest first for processing)
    fills = sorted(trades.values(), key=lambda x: x.get("timestamp", 0))

    # Track open positions per asset: {asset: [(fill, remaining_size), ...]}
    open_positions = {}
    round_trips = []

    for fill in fills:
        asset = fill["asset"]
        size = fill["size"]
        action = fill["action"]
        direction = fill["direction"]

        if asset not in open_positions:
            open_positions[asset] = []

        if action == "open":
            # Add to open positions
            open_positions[asset].append({
                "fill": fill,
                "remaining": size
            })
        elif action == "close" and open_positions[asset]:
            # Match with open positions (FIFO)
            close_size = size
            entry_fills = []
            total_entry_value = 0
            total_entry_size = 0

            while close_size > 0 and open_positions[asset]:
                open_pos = open_positions[asset][0]
                open_fill = open_pos["fill"]
                available = open_pos["remaining"]

                matched_size = min(close_size, available)
                # Calculate proportional fee based on matched size
                original_size = open_fill["size"]
                proportional_fee = open_fill["fee"] * (matched_size / original_size) if original_size > 0 else 0
                entry_fills.append({
                    "id": open_fill["id"],
                    "price": open_fill["price"],
                    "size": matched_size,
                    "timestamp": open_fill["timestamp"],
                    "fee": proportional_fee
                })
                total_entry_value += open_fill["price"] * matched_size
                total_entry_size += matched_size

                open_pos["remaining"] -= matched_size
                close_size -= matched_size

                if open_pos["remaining"] <= 0:
                    open_positions[asset].pop(0)

            if total_entry_size > 0:
                avg_entry = total_entry_value / total_entry_size
                exit_price = fill["price"]

                # Combine notes from entry and exit fills
                all_notes = []
                for ef in entry_fills:
                    entry_trade = trades.get(ef["id"], {})
                    if entry_trade.get("notes"):
                        all_notes.append(entry_trade["notes"])
                if fill.get("notes"):
                    all_notes.append(fill["notes"])

                # Determine market type (spot assets start with @)
                market_type = "spot" if asset.startswith("@") else "perp"
                display_name = get_spot_name(asset) if market_type == "spot" else asset

                round_trip = {
                    "id": f"rt_{fill['id']}",
                    "asset": asset,
                    "display_name": display_name,
                    "market_type": market_type,
                    "direction": direction,
                    "entry_price": round(avg_entry, 6),
                    "exit_price": round(exit_price, 6),
                    "size": round(total_entry_size, 6),
                    "pnl": round(fill.get("pnl", 0), 2),
                    "fees": round(sum(ef.get("fee", 0) for ef in entry_fills) + fill.get("fee", 0), 2),
                    "entry_time": entry_fills[0]["timestamp"] if entry_fills else fill["timestamp"],
                    "exit_time": fill["timestamp"],
                    "duration_ms": fill["timestamp"] - (entry_fills[0]["timestamp"] if entry_fills else fill["timestamp"]),
                    "entry_fill_ids": [ef["id"] for ef in entry_fills],
                    "exit_fill_id": fill["id"],
                    "notes": " | ".join(all_notes) if all_notes else ""
                }
                round_trips.append(round_trip)

    # Sort by exit time, newest first
    round_trips.sort(key=lambda x: x["exit_time"], reverse=True)
    return round_trips


def update_round_trip_notes(round_trip_id: str, notes: str) -> bool:
    """
    Update notes for a round trip (stores on the exit fill).

    Args:
        round_trip_id: The round trip ID (rt_<exit_fill_id>)
        notes: The new notes content

    Returns:
        True if successful, False if not found
    """
    if not round_trip_id.startswith("rt_"):
        return False

    exit_fill_id = round_trip_id[3:]  # Remove "rt_" prefix
    return update_trade_notes(exit_fill_id, notes)


def get_unique_assets() -> list:
    """Get list of unique assets from all trades with display names."""
    trades = load_trades()
    assets = set(t.get("asset", "") for t in trades.values())
    result = []
    for asset in sorted([a for a in assets if a]):
        display_name = get_spot_name(asset) if asset.startswith("@") else asset
        result.append({"id": asset, "name": display_name})
    return result
