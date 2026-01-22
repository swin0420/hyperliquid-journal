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
    get_unique_assets,
    get_stored_wallet
)

app = Flask(__name__)


@app.route("/")
def index():
    """Serve the main journal page."""
    return render_template("index.html")


@app.route("/api/trades", methods=["GET"])
def get_trades():
    """Get all stored trades sorted by timestamp (newest first)."""
    trades = get_trades_sorted(descending=True)
    return jsonify(trades)


@app.route("/api/trades/sync", methods=["POST"])
def sync_trades():
    """
    Sync trades from Hyperliquid API.
    Optionally accepts a wallet address in the request body.
    Clears existing trades if wallet address changed.
    """
    data = request.get_json() or {}
    wallet = data.get("wallet_address") or WALLET_ADDRESS

    if not wallet:
        return jsonify({"error": "No wallet address configured"}), 400

    try:
        new_trades = fetch_and_parse_trades(wallet)

        # Clear existing trades if wallet changed
        stored_wallet = get_stored_wallet()
        if stored_wallet and stored_wallet.lower() != wallet.lower():
            existing = {}
        else:
            existing = load_trades()

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

    # Handle round trip notes (stored on exit fill)
    if trade_id.startswith("rt_"):
        success = update_round_trip_notes(trade_id, data["notes"])
    else:
        success = update_trade_notes(trade_id, data["notes"])

    if success:
        return jsonify({"message": "Notes updated"})
    else:
        return jsonify({"error": "Trade not found"}), 404


@app.route("/api/roundtrips", methods=["GET"])
def get_roundtrips():
    """Get all round-trip trades (paired entry/exit)."""
    round_trips = get_round_trips()
    return jsonify(round_trips)


@app.route("/api/assets", methods=["GET"])
def get_assets():
    """Get list of unique traded assets."""
    assets = get_unique_assets()
    return jsonify(assets)


@app.route("/api/funding", methods=["GET"])
def get_funding():
    """Get funding payment events."""
    wallet = request.args.get("wallet") or WALLET_ADDRESS
    if not wallet:
        return jsonify({"error": "No wallet address configured"}), 400

    try:
        events = fetch_funding_events(wallet)
        return jsonify(events)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/positions", methods=["GET"])
def get_positions():
    """Get current open positions."""
    wallet = request.args.get("wallet") or WALLET_ADDRESS
    if not wallet:
        return jsonify({"error": "No wallet address configured"}), 400

    try:
        positions = fetch_open_positions(wallet)
        return jsonify(positions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["GET"])
def get_config():
    """Get current configuration (wallet address)."""
    return jsonify({
        "wallet_address": WALLET_ADDRESS,
        "configured": bool(WALLET_ADDRESS)
    })


@app.route("/api/config", methods=["PUT"])
def update_config():
    """
    Update wallet address for the session.
    Note: This only updates in memory, not the .env file.
    """
    global WALLET_ADDRESS
    data = request.get_json()
    if data and "wallet_address" in data:
        # Import and update the config module
        import config
        config.WALLET_ADDRESS = data["wallet_address"]
        return jsonify({"message": "Wallet address updated"})
    return jsonify({"error": "wallet_address required"}), 400


if __name__ == "__main__":
    app.run(debug=True, port=5001)
