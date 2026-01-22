import os
from sqlalchemy import create_engine, Column, String, Float, Integer, Text, BigInteger, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL
from hyperliquid import get_spot_name

Base = declarative_base()


class Trade(Base):
    __tablename__ = 'trades'

    id = Column(String, primary_key=True)
    wallet_address = Column(String, nullable=False, index=True)
    asset = Column(String, nullable=False)
    direction = Column(String)
    action = Column(String)
    size = Column(Float)
    price = Column(Float)
    pnl = Column(Float, default=0)
    fee = Column(Float, default=0)
    timestamp = Column(BigInteger)
    notes = Column(Text, default="")

    __table_args__ = (
        Index('idx_wallet_timestamp', 'wallet_address', 'timestamp'),
    )


# Database setup
engine = None
SessionLocal = None

def init_db():
    """Initialize database connection."""
    global engine, SessionLocal
    if not DATABASE_URL:
        return False

    # Railway uses postgres:// but SQLAlchemy needs postgresql+psycopg://
    db_url = DATABASE_URL.replace("postgres://", "postgresql+psycopg://").replace("postgresql://", "postgresql+psycopg://")
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return True


def get_session():
    """Get a database session."""
    if not SessionLocal:
        if not init_db():
            return None
    return SessionLocal()


def load_trades(wallet_address: str) -> dict:
    """Load trades for a specific wallet from database."""
    session = get_session()
    if not session:
        return {}

    try:
        trades = session.query(Trade).filter(Trade.wallet_address == wallet_address.lower()).all()
        return {t.id: {
            "id": t.id,
            "asset": t.asset,
            "direction": t.direction,
            "action": t.action,
            "size": t.size,
            "price": t.price,
            "pnl": t.pnl,
            "fee": t.fee,
            "timestamp": t.timestamp,
            "notes": t.notes or ""
        } for t in trades}
    finally:
        session.close()


def save_trades(trades: dict, wallet_address: str):
    """Save trades for a specific wallet to database."""
    session = get_session()
    if not session:
        return

    wallet = wallet_address.lower()

    try:
        for trade_id, trade_data in trades.items():
            existing = session.query(Trade).filter(Trade.id == trade_id).first()
            if existing:
                # Update existing trade
                existing.asset = trade_data.get("asset", "")
                existing.direction = trade_data.get("direction", "")
                existing.action = trade_data.get("action", "")
                existing.size = trade_data.get("size", 0)
                existing.price = trade_data.get("price", 0)
                existing.pnl = trade_data.get("pnl", 0)
                existing.fee = trade_data.get("fee", 0)
                existing.timestamp = trade_data.get("timestamp", 0)
                existing.notes = trade_data.get("notes", "")
            else:
                # Create new trade
                trade = Trade(
                    id=trade_id,
                    wallet_address=wallet,
                    asset=trade_data.get("asset", ""),
                    direction=trade_data.get("direction", ""),
                    action=trade_data.get("action", ""),
                    size=trade_data.get("size", 0),
                    price=trade_data.get("price", 0),
                    pnl=trade_data.get("pnl", 0),
                    fee=trade_data.get("fee", 0),
                    timestamp=trade_data.get("timestamp", 0),
                    notes=trade_data.get("notes", "")
                )
                session.add(trade)
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def merge_trades(existing: dict, new_trades: list) -> dict:
    """Merge new trades with existing trades, preserving notes."""
    for trade in new_trades:
        trade_id = trade["id"]
        if trade_id in existing:
            trade["notes"] = existing[trade_id].get("notes", "")
        existing[trade_id] = trade
    return existing


def update_trade_notes(trade_id: str, notes: str, wallet_address: str) -> bool:
    """Update notes for a specific trade."""
    session = get_session()
    if not session:
        return False

    try:
        trade = session.query(Trade).filter(
            Trade.id == trade_id,
            Trade.wallet_address == wallet_address.lower()
        ).first()

        if not trade:
            return False

        trade.notes = notes
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def get_trades_sorted(wallet_address: str, descending: bool = True) -> list:
    """Get all trades for a wallet sorted by timestamp."""
    trades = load_trades(wallet_address)
    trade_list = list(trades.values())
    trade_list.sort(key=lambda x: x.get("timestamp", 0), reverse=descending)
    return trade_list


def get_round_trips(wallet_address: str) -> list:
    """Group individual fills into round-trip trades."""
    trades = load_trades(wallet_address)
    if not trades:
        return []

    fills = sorted(trades.values(), key=lambda x: x.get("timestamp", 0))
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
            open_positions[asset].append({
                "fill": fill,
                "remaining": size
            })
        elif action == "close" and open_positions[asset]:
            close_size = size
            entry_fills = []
            total_entry_value = 0
            total_entry_size = 0

            while close_size > 0 and open_positions[asset]:
                open_pos = open_positions[asset][0]
                open_fill = open_pos["fill"]
                available = open_pos["remaining"]

                matched_size = min(close_size, available)
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

                all_notes = []
                for ef in entry_fills:
                    entry_trade = trades.get(ef["id"], {})
                    if entry_trade.get("notes"):
                        all_notes.append(entry_trade["notes"])
                if fill.get("notes"):
                    all_notes.append(fill["notes"])

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

    round_trips.sort(key=lambda x: x["exit_time"], reverse=True)
    return round_trips


def update_round_trip_notes(round_trip_id: str, notes: str, wallet_address: str) -> bool:
    """Update notes for a round trip."""
    if not round_trip_id.startswith("rt_"):
        return False
    exit_fill_id = round_trip_id[3:]
    return update_trade_notes(exit_fill_id, notes, wallet_address)


def get_unique_assets(wallet_address: str) -> list:
    """Get list of unique assets from all trades for a wallet."""
    trades = load_trades(wallet_address)
    assets = set(t.get("asset", "") for t in trades.values())
    result = []
    for asset in sorted([a for a in assets if a]):
        display_name = get_spot_name(asset) if asset.startswith("@") else asset
        result.append({"id": asset, "name": display_name})
    return result


# Legacy functions for backward compatibility
def get_stored_wallet() -> str:
    """Deprecated - wallet is now per-request."""
    return None
