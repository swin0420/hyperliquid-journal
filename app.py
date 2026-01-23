from flask import Flask, jsonify, request, render_template
from config import WALLET_ADDRESS
from hyperliquid import fetch_and_parse_trades, fetch_funding_events, fetch_open_positions
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


def get_wallet_from_request():
    """Get wallet address from request (query param, body, or header)."""
    # Try query param first
    wallet = request.args.get("wallet")
    # Then try JSON body
    if not wallet and request.is_json:
        data = request.get_json(silent=True) or {}
        wallet = data.get("wallet_address") or data.get("wallet")
    # Then try header
    if not wallet:
        wallet = request.headers.get("X-Wallet-Address")
    return wallet


@app.route("/")
def index():
    """Serve the main journal page."""
    return render_template("index.html")


@app.route("/api/trades", methods=["GET"])
def get_trades():
    """Get all stored trades for a wallet sorted by timestamp (newest first)."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": "Wallet address required"}), 400

    trades = get_trades_sorted(wallet, descending=True)
    return jsonify(trades)


@app.route("/api/trades/sync", methods=["POST"])
def sync_trades():
    """Sync trades from Hyperliquid API for a specific wallet."""
    data = request.get_json() or {}
    wallet = data.get("wallet_address")

    if not wallet:
        return jsonify({"error": "No wallet address provided"}), 400

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
        return jsonify({"error": str(e)}), 500


@app.route("/api/trades/<trade_id>/notes", methods=["PUT"])
def update_notes(trade_id: str):
    """Update notes for a specific trade or round trip."""
    data = request.get_json()
    if not data or "notes" not in data:
        return jsonify({"error": "Notes field required"}), 400

    wallet = data.get("wallet_address") or get_wallet_from_request()
    if not wallet:
        return jsonify({"error": "Wallet address required"}), 400

    # Handle round trip notes (stored on exit fill)
    if trade_id.startswith("rt_"):
        success = update_round_trip_notes(trade_id, data["notes"], wallet)
    else:
        success = update_trade_notes(trade_id, data["notes"], wallet)

    if success:
        return jsonify({"message": "Notes updated"})
    else:
        return jsonify({"error": "Trade not found"}), 404


@app.route("/api/init", methods=["GET"])
def init_data():
    """Get initial data (roundtrips + assets) in a single call."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": "Wallet address required"}), 400

    return jsonify({
        "roundtrips": get_round_trips(wallet),
        "assets": get_unique_assets(wallet)
    })


@app.route("/api/roundtrips", methods=["GET"])
def get_roundtrips():
    """Get all round-trip trades (paired entry/exit) for a wallet."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": "Wallet address required"}), 400

    round_trips = get_round_trips(wallet)
    return jsonify(round_trips)


@app.route("/api/assets", methods=["GET"])
def get_assets():
    """Get list of unique traded assets for a wallet."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": "Wallet address required"}), 400

    assets = get_unique_assets(wallet)
    return jsonify(assets)


@app.route("/api/funding", methods=["GET"])
def get_funding():
    """Get funding payment events."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": "No wallet address provided"}), 400

    try:
        events = fetch_funding_events(wallet)
        return jsonify(events)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/positions", methods=["GET"])
def get_positions():
    """Get current open positions."""
    wallet = get_wallet_from_request()
    if not wallet:
        return jsonify({"error": "No wallet address provided"}), 400

    try:
        positions = fetch_open_positions(wallet)
        return jsonify(positions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)
