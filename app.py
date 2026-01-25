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
from config import (
    DATABASE_URL,
    ANTHROPIC_API_KEY,
    DISCORD_WEBHOOK_URL,
    CRYPTOPANIC_API_KEY,
    SENTIMENT_POLL_INTERVAL,
    SENTIMENT_BOT_NAME
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


# =============================================================================
# Sentiment Bot Endpoints
# =============================================================================

def _get_sentiment_bot():
    """Get or create the sentiment bot instance."""
    from sentiment import get_sentiment_bot, create_sentiment_bot

    bot = get_sentiment_bot()
    if bot is None and all([DATABASE_URL, ANTHROPIC_API_KEY, DISCORD_WEBHOOK_URL]):
        bot = create_sentiment_bot(
            database_url=DATABASE_URL,
            anthropic_api_key=ANTHROPIC_API_KEY,
            discord_webhook_url=DISCORD_WEBHOOK_URL,
            cryptopanic_api_key=CRYPTOPANIC_API_KEY,
            poll_interval=SENTIMENT_POLL_INTERVAL
        )
    return bot


def _check_sentiment_config() -> tuple[bool, str]:
    """Check if sentiment bot is properly configured."""
    missing = []
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not DISCORD_WEBHOOK_URL:
        missing.append("DISCORD_WEBHOOK_URL")

    if missing:
        return False, f"Missing config: {', '.join(missing)}"
    return True, ""


@app.route("/api/signals", methods=["GET"])
def get_signals():
    """Get sentiment signal history."""
    # Optional filters
    limit = request.args.get("limit", 50, type=int)
    sentiment = request.args.get("sentiment")
    asset = request.args.get("asset")
    actionable_only = request.args.get("actionable", "false").lower() == "true"

    try:
        from sentiment import get_sentiment_session, SignalRepository, init_sentiment_db

        if not init_sentiment_db(DATABASE_URL):
            return jsonify({"error": "Database not configured"}), 500

        session = get_sentiment_session()
        if not session:
            return jsonify({"error": "Could not connect to database"}), 500

        try:
            repo = SignalRepository(session)
            signals = repo.get_recent_signals(
                limit=min(limit, 200),
                sentiment=sentiment,
                asset=asset.upper() if asset else None,
                actionable_only=actionable_only
            )

            return jsonify({
                "signals": [s.to_dict() for s in signals],
                "count": len(signals)
            })
        finally:
            session.close()

    except Exception as e:
        logger.exception("Failed to fetch signals: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/signals/stats", methods=["GET"])
def get_signal_stats():
    """Get sentiment signal statistics."""
    hours = request.args.get("hours", 24, type=int)

    try:
        from sentiment import get_sentiment_session, SignalRepository, init_sentiment_db

        if not init_sentiment_db(DATABASE_URL):
            return jsonify({"error": "Database not configured"}), 500

        session = get_sentiment_session()
        if not session:
            return jsonify({"error": "Could not connect to database"}), 500

        try:
            repo = SignalRepository(session)
            stats = repo.get_signal_stats(hours=min(hours, 168))  # Max 1 week
            return jsonify(stats)
        finally:
            session.close()

    except Exception as e:
        logger.exception("Failed to fetch signal stats: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/signals/enable", methods=["POST"])
def enable_sentiment_bot():
    """Enable the sentiment analysis bot."""
    # Check configuration
    configured, error_msg = _check_sentiment_config()
    if not configured:
        return jsonify({"error": error_msg}), 400

    data = request.get_json() or {}
    poll_interval = data.get("poll_interval", SENTIMENT_POLL_INTERVAL)

    # Validate interval (1-60 minutes)
    if not isinstance(poll_interval, int) or poll_interval < 60 or poll_interval > 3600:
        return jsonify({"error": "Poll interval must be between 60 and 3600 seconds"}), 400

    try:
        bot = _get_sentiment_bot()
        if bot is None:
            return jsonify({"error": "Failed to create bot instance"}), 500

        if bot.is_running():
            return jsonify({
                "message": "Sentiment bot is already running",
                "stats": bot.get_stats()
            })

        # Update interval if different
        if poll_interval != bot.poll_interval:
            bot.set_poll_interval(poll_interval)

        success = bot.start(send_startup_message=True)

        if success:
            return jsonify({
                "message": "Sentiment bot started",
                "poll_interval": bot.poll_interval,
                "stats": bot.get_stats()
            })
        else:
            return jsonify({"error": "Failed to start sentiment bot"}), 500

    except Exception as e:
        logger.exception("Failed to enable sentiment bot: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/signals/disable", methods=["POST"])
def disable_sentiment_bot():
    """Disable the sentiment analysis bot."""
    try:
        from sentiment import get_sentiment_bot

        bot = get_sentiment_bot()
        if bot is None or not bot.is_running():
            return jsonify({"message": "Sentiment bot is not running"})

        success = bot.stop(send_shutdown_message=True)

        if success:
            return jsonify({"message": "Sentiment bot stopped"})
        else:
            return jsonify({"error": "Failed to stop sentiment bot"}), 500

    except Exception as e:
        logger.exception("Failed to disable sentiment bot: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/signals/status", methods=["GET"])
def get_sentiment_status():
    """Get sentiment bot status."""
    configured, error_msg = _check_sentiment_config()

    try:
        from sentiment import get_sentiment_bot

        bot = get_sentiment_bot()

        return jsonify({
            "configured": configured,
            "config_error": error_msg if not configured else None,
            "is_running": bot.is_running() if bot else False,
            "stats": bot.get_stats() if bot else None
        })

    except Exception as e:
        logger.exception("Failed to get sentiment status: %s", e)
        return jsonify({
            "configured": configured,
            "config_error": error_msg if not configured else None,
            "is_running": False,
            "error": str(e)
        })


@app.route("/api/signals/poll", methods=["POST"])
def trigger_sentiment_poll():
    """Trigger an immediate sentiment poll."""
    try:
        from sentiment import get_sentiment_bot

        bot = get_sentiment_bot()
        if bot is None or not bot.is_running():
            return jsonify({"error": "Sentiment bot is not running"}), 400

        result = bot.poll_now()
        return jsonify(result)

    except Exception as e:
        logger.exception("Failed to trigger poll: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/signals/test", methods=["POST"])
def test_sentiment_alert():
    """Send a test alert to Discord."""
    configured, error_msg = _check_sentiment_config()
    if not configured:
        return jsonify({"error": error_msg}), 400

    try:
        bot = _get_sentiment_bot()
        if bot is None:
            return jsonify({"error": "Failed to create bot instance"}), 500

        success = bot.send_test_alert()

        if success:
            return jsonify({"message": "Test alert sent to Discord"})
        else:
            return jsonify({"error": "Failed to send test alert"}), 500

    except Exception as e:
        logger.exception("Failed to send test alert: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/signals/webhook/test", methods=["POST"])
def test_discord_webhook():
    """Test Discord webhook connection."""
    configured, error_msg = _check_sentiment_config()
    if not configured:
        return jsonify({"error": error_msg}), 400

    try:
        bot = _get_sentiment_bot()
        if bot is None:
            return jsonify({"error": "Failed to create bot instance"}), 500

        success = bot.test_discord()

        if success:
            return jsonify({"message": "Discord webhook is working"})
        else:
            return jsonify({"error": "Discord webhook test failed"}), 500

    except Exception as e:
        logger.exception("Failed to test webhook: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/signals/debug", methods=["GET"])
def debug_sentiment():
    """Debug endpoint to see raw news fetching and analysis pipeline."""
    analyze_sample = request.args.get("analyze", "false").lower() == "true"

    try:
        from sentiment import NewsAggregator, SentimentAnalyzer
        from sentiment import get_sentiment_session, SignalRepository, init_sentiment_db

        result = {
            "cryptopanic_configured": bool(CRYPTOPANIC_API_KEY),
            "anthropic_configured": bool(ANTHROPIC_API_KEY),
            "discord_configured": bool(DISCORD_WEBHOOK_URL),
            "database_configured": bool(DATABASE_URL),
            "news_sources": [],
            "total_fetched": 0,
            "new_items": 0,
            "already_processed": 0,
            "sample_analysis": None
        }

        # Create aggregator and fetch news
        aggregator = NewsAggregator(
            cryptopanic_api_key=CRYPTOPANIC_API_KEY,
            filter_by_assets=True
        )

        # Fetch from each source
        all_items = []

        # CryptoPanic
        try:
            cp_items = aggregator.fetch_cryptopanic(limit=10)
            result["news_sources"].append({
                "source": "cryptopanic",
                "status": "ok",
                "count": len(cp_items),
                "items": [{"id": i.id, "title": i.title[:80], "assets": i.currencies, "published": i.published_at.isoformat()} for i in cp_items[:5]]
            })
            all_items.extend(cp_items)
        except Exception as e:
            result["news_sources"].append({
                "source": "cryptopanic",
                "status": "error",
                "error": str(e)
            })

        # CryptoCompare
        try:
            cc_items = aggregator.fetch_cryptonews(limit=10)
            result["news_sources"].append({
                "source": "cryptocompare",
                "status": "ok",
                "count": len(cc_items),
                "items": [{"id": i.id, "title": i.title[:80], "assets": i.currencies, "published": i.published_at.isoformat()} for i in cc_items[:5]]
            })
            all_items.extend(cc_items)
        except Exception as e:
            result["news_sources"].append({
                "source": "cryptocompare",
                "status": "error",
                "error": str(e)
            })

        result["total_fetched"] = len(all_items)

        # Check which items are new (not in DB)
        if DATABASE_URL and init_sentiment_db(DATABASE_URL):
            session = get_sentiment_session()
            if session:
                try:
                    repo = SignalRepository(session)
                    new_items = [item for item in all_items if not repo.news_exists(item.id)]
                    result["new_items"] = len(new_items)
                    result["already_processed"] = len(all_items) - len(new_items)

                    # Sample analysis if requested
                    # Use force=true to analyze even already-processed items
                    force_analyze = request.args.get("force", "false").lower() == "true"
                    items_to_analyze = new_items if new_items else (all_items if force_analyze else [])

                    if analyze_sample and items_to_analyze and ANTHROPIC_API_KEY:
                        analyzer = SentimentAnalyzer(api_key=ANTHROPIC_API_KEY)
                        sample = items_to_analyze[0]
                        analysis = analyzer.analyze_single(sample)
                        if analysis:
                            result["sample_analysis"] = {
                                "news_id": analysis.news_id,
                                "title": analysis.title,
                                "sentiment": analysis.sentiment.value,
                                "confidence": analysis.confidence,
                                "signal_strength": analysis.signal_strength.value,
                                "is_actionable": analysis.is_actionable,
                                "assets": analysis.assets,
                                "reasoning": analysis.reasoning,
                                "price_impact": analysis.price_impact,
                                "timeframe": analysis.timeframe
                            }
                        result["analyzed_from"] = "new" if new_items else "existing (forced)"
                finally:
                    session.close()

        return jsonify(result)

    except Exception as e:
        logger.exception("Debug endpoint error: %s", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)
