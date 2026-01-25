import re
import atexit
import logging
from flask import Flask, jsonify, request, render_template
from hyperliquid import fetch_and_parse_trades, fetch_funding_events, fetch_open_positions
from constants import ErrorMsg, ROUND_TRIP_PREFIX
from scheduler import (
    start_scheduler,
    stop_scheduler,
    register_wallet_for_sync,
    unregister_wallet,
    is_wallet_registered
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
from storage import (
    load_trades,
    save_trades,
    merge_trades,
    update_trade_notes,
    get_trades_sorted,
    get_round_trips,
    update_round_trip_notes,
    get_unique_assets
)

app = Flask(__name__)

# Start background scheduler only in main process (not in gunicorn workers)
import os
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
    # Only start if we're the main process or in production
    # Use a file lock to prevent multiple schedulers in gunicorn
    _scheduler_started = False
    try:
        start_scheduler()
        _scheduler_started = True
        atexit.register(stop_scheduler)
    except Exception as e:
        logger.warning("Scheduler already running or failed to start: %s", e)

# Ethereum address pattern: 0x followed by 40 hex characters
WALLET_PATTERN = re.compile(r'^0x[a-fA-F0-9]{40}$')


def is_valid_wallet(wallet: str) -> bool:
    """Validate Ethereum wallet address format."""
    return bool(wallet and WALLET_PATTERN.match(wallet))


def get_wallet_from_request() -> str | None:
    """Get and validate wallet address from request (query param, body, or header)."""
    # Try query param first
    wallet = request.args.get("wallet")
    # Then try JSON body
    if not wallet and request.is_json:
        data = request.get_json(silent=True) or {}
        wallet = data.get("wallet_address") or data.get("wallet")
    # Then try header
    if not wallet:
        wallet = request.headers.get("X-Wallet-Address")

    # Validate format
    if wallet and not is_valid_wallet(wallet):
        return None

    return wallet


@app.route("/")
def index():
    """Serve the main journal page."""
    return render_template("index.html")


@app.route("/health")
def health_check():
    """Health check endpoint for Railway."""
    return jsonify({"status": "healthy"}), 200


@app.route("/api/trades", methods=["GET"])
def get_trades():
    """Get all stored trades for a wallet sorted by timestamp (newest first)."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_REQUIRED}), 400

    trades = get_trades_sorted(wallet, descending=True)
    return jsonify(trades)


@app.route("/api/trades/sync", methods=["POST"])
def sync_trades():
    """Sync trades from Hyperliquid API for a specific wallet."""
    data = request.get_json() or {}
    wallet = data.get("wallet_address")

    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_NOT_PROVIDED}), 400

    if not is_valid_wallet(wallet):
        return jsonify({"error": ErrorMsg.WALLET_INVALID}), 400

    try:
        new_trades = fetch_and_parse_trades(wallet)
        existing = load_trades(wallet)
        merged = merge_trades(existing, new_trades)
        save_trades(merged, wallet)

        return jsonify({
            "message": f"Synced {len(new_trades)} trades",
            "total_trades": len(merged)
        })
    except Exception as e:
        logger.exception("Failed to sync trades for wallet %s", wallet)
        return jsonify({"error": str(e)}), 500


@app.route("/api/trades/<trade_id>/notes", methods=["PUT"])
def update_notes(trade_id: str):
    """Update notes for a specific trade or round trip."""
    data = request.get_json()
    if not data or "notes" not in data:
        return jsonify({"error": ErrorMsg.NOTES_REQUIRED}), 400

    wallet = data.get("wallet_address") or get_wallet_from_request()
    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_REQUIRED}), 400

    # Handle round trip notes (stored on exit fill)
    if trade_id.startswith(ROUND_TRIP_PREFIX):
        success = update_round_trip_notes(trade_id, data["notes"], wallet)
    else:
        success = update_trade_notes(trade_id, data["notes"], wallet)

    if success:
        return jsonify({"message": "Notes updated"})
    else:
        return jsonify({"error": ErrorMsg.TRADE_NOT_FOUND}), 404


@app.route("/api/init", methods=["GET"])
def init_data():
    """Get initial data (roundtrips + assets) in a single call."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_REQUIRED}), 400

    return jsonify({
        "roundtrips": get_round_trips(wallet),
        "assets": get_unique_assets(wallet)
    })


@app.route("/api/roundtrips", methods=["GET"])
def get_roundtrips():
    """Get all round-trip trades (paired entry/exit) for a wallet."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_REQUIRED}), 400

    round_trips = get_round_trips(wallet)
    return jsonify(round_trips)


@app.route("/api/assets", methods=["GET"])
def get_assets():
    """Get list of unique traded assets for a wallet."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_REQUIRED}), 400

    assets = get_unique_assets(wallet)
    return jsonify(assets)


@app.route("/api/funding", methods=["GET"])
def get_funding():
    """Get funding payment events."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_NOT_PROVIDED}), 400

    try:
        events = fetch_funding_events(wallet)
        return jsonify(events)
    except Exception as e:
        logger.exception("Failed to fetch funding for wallet %s", wallet)
        return jsonify({"error": str(e)}), 500


@app.route("/api/positions", methods=["GET"])
def get_positions():
    """Get current open positions."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_NOT_PROVIDED}), 400

    try:
        positions = fetch_open_positions(wallet)
        return jsonify(positions)
    except Exception as e:
        logger.exception("Failed to fetch positions for wallet %s", wallet)
        return jsonify({"error": str(e)}), 500


def _background_sync(wallet_address: str) -> None:
    """Background sync function called by scheduler."""
    try:
        logger.info("Background sync starting for wallet %s", wallet_address[:10])
        new_trades = fetch_and_parse_trades(wallet_address)
        existing = load_trades(wallet_address)
        merged = merge_trades(existing, new_trades)
        save_trades(merged, wallet_address)
        logger.info("Background sync completed for wallet %s: %d trades", wallet_address[:10], len(new_trades))
    except Exception as e:
        logger.exception("Background sync failed for wallet %s: %s", wallet_address[:10], e)


@app.route("/api/sync/enable", methods=["POST"])
def enable_background_sync():
    """Enable background sync for a wallet."""
    data = request.get_json() or {}
    wallet = data.get("wallet_address")

    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_NOT_PROVIDED}), 400

    if not is_valid_wallet(wallet):
        return jsonify({"error": ErrorMsg.WALLET_INVALID}), 400

    interval = data.get("interval_minutes", 5)
    if not isinstance(interval, int) or interval < 1 or interval > 60:
        return jsonify({"error": "Interval must be between 1 and 60 minutes"}), 400

    newly_registered = register_wallet_for_sync(wallet, _background_sync, interval)

    return jsonify({
        "message": "Background sync enabled" if newly_registered else "Background sync already enabled",
        "interval_minutes": interval
    })


@app.route("/api/sync/disable", methods=["POST"])
def disable_background_sync():
    """Disable background sync for a wallet."""
    data = request.get_json() or {}
    wallet = data.get("wallet_address")

    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_NOT_PROVIDED}), 400

    if not is_valid_wallet(wallet):
        return jsonify({"error": ErrorMsg.WALLET_INVALID}), 400

    removed = unregister_wallet(wallet)

    return jsonify({
        "message": "Background sync disabled" if removed else "Background sync was not enabled"
    })


@app.route("/api/sync/status", methods=["GET"])
def get_sync_status():
    """Check if background sync is enabled for a wallet."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": ErrorMsg.WALLET_REQUIRED}), 400

    return jsonify({
        "enabled": is_wallet_registered(wallet)
    })


if __name__ == "__main__":
    app.run(debug=True, port=5001)
