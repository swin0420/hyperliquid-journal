# Hyperliquid Trade Journal

## Overview
A multi-user trading journal web app for tracking Hyperliquid perpetual futures and spot trades. Features anime-styled UI with Nekopara catgirls (Chocola & Vanilla).

**Live Site**: https://hl-journal.xyz

## Tech Stack
- **Backend**: Python Flask, SQLAlchemy, APScheduler
- **Server**: Gunicorn (1 worker, 2 threads)
- **Database**: PostgreSQL (Railway) with connection pooling
- **Frontend**: Vanilla JS, HTML, CSS, Chart.js
- **Styling**: Aurora/Northern Lights animated background, glassmorphism cards
- **Fonts**: Inter (UI), JetBrains Mono (numbers)
- **Deployment**: Railway (auto-deploy from GitHub)

## Project Structure
```
trade-journal/
├── app.py              # Flask routes and API endpoints
├── config.py           # Configuration (DATABASE_URL)
├── constants.py        # Enums and constants (Direction, Action, MarketType, etc.)
├── hyperliquid.py      # Hyperliquid API integration with retries
├── scheduler.py        # Background sync with APScheduler
├── storage.py          # PostgreSQL storage with SQLAlchemy + connection pooling
├── requirements.txt    # Python dependencies
├── Procfile            # Railway deployment config
├── templates/
│   └── index.html      # Main page template
└── static/
    ├── style.css       # Styles with Aurora background
    ├── app.js          # Frontend JavaScript
    ├── catgirl-left.png    # Chocola (desktop)
    ├── catgirl-right.png   # Vanilla (desktop)
    └── catgirls-mobile.gif # Animated gif (mobile)
```

## Key Features
- **Multi-user**: Each wallet's data stored privately in PostgreSQL
- Sync trades from Hyperliquid API by wallet address
- Track P&L, fees, funding, win rate, best win streak
- Open positions display with current price and unrealized P&L
- Cumulative P&L chart
- Period comparison (this month vs last month)
- Trade filtering (by date, asset, market type, P&L)
- Trade notes
- Supports both perps and spot markets

## API Endpoints
All endpoints require wallet address (query param, body, or header). Wallet must be valid Ethereum format (0x + 40 hex chars).

- `GET /` - Main journal page
- `GET /health` - Health check endpoint (for Railway monitoring)
- `GET /api/init?wallet=0x...` - Get roundtrips + assets (combined, faster)
- `GET /api/trades?wallet=0x...` - Get all trades
- `POST /api/trades/sync` - Sync trades from Hyperliquid
- `GET /api/roundtrips?wallet=0x...` - Get round-trip trades
- `GET /api/positions?wallet=0x...` - Get open positions with current prices
- `GET /api/funding?wallet=0x...` - Get funding history
- `GET /api/assets?wallet=0x...` - Get unique traded assets
- `PUT /api/trades/<id>/notes` - Update trade notes
- `POST /api/sync/enable` - Enable background sync for wallet (body: wallet_address, interval_minutes)
- `POST /api/sync/disable` - Disable background sync for wallet
- `GET /api/sync/status?wallet=0x...` - Check if background sync is enabled

## UI Features
- Aurora animated background (purple, pink, green, cyan gradients)
- Floating Chocola & Vanilla catgirls with hover animations (desktop)
- Animated Chocola gif (mobile)
- Tap to expand/collapse trade cards (mobile)
- Dark theme with glassmorphism cards
- Responsive design

## Database Schema
```sql
trades (
    id VARCHAR PRIMARY KEY,
    wallet_address VARCHAR NOT NULL,
    asset VARCHAR,
    direction VARCHAR,
    action VARCHAR,
    size FLOAT,
    price FLOAT,
    pnl FLOAT,
    fee FLOAT,
    timestamp BIGINT,
    notes TEXT
)
```

## Running Locally
```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql://...  # Optional, for PostgreSQL
python app.py
# Open http://localhost:5001
```

## Deployment
- **Hosting**: Railway
- **Domain**: hl-journal.xyz (Namecheap DNS → Railway CNAME)
- **SSL**: Let's Encrypt (auto-issued by Railway)
- **Database**: Railway PostgreSQL
- **Repository**: https://github.com/swin0420/hyperliquid-journal

## Gunicorn Configuration
```
web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120 --keep-alive 5
```
- **workers 1**: Single worker prevents APScheduler conflicts (multiple schedulers)
- **threads 2**: Allow concurrent request handling within single worker
- **timeout 120**: Long timeout for slow Hyperliquid API calls
- **keep-alive 5**: Connection reuse for better mobile performance

## Environment Variables
- `DATABASE_URL` - PostgreSQL connection string (required for production)

## Performance Optimizations
- **Parallel API calls**: Hyperliquid API calls (clearinghouseState, allMids, openOrders) run concurrently
- **Sync cooldown**: Auto-sync skipped if synced within 30 seconds (per-wallet)
- **Combined endpoint**: `/api/init` returns roundtrips + assets in single request
- **Image preloading**: Desktop catgirl images preloaded for faster display
- **Connection pooling**: PostgreSQL QueuePool (5 connections, 10 overflow, pre-ping enabled)
- **Round-trip caching**: 30-second TTL cache with automatic invalidation on updates
- **API retries**: 3 retries with exponential backoff (0.5s factor) on 429/5xx errors
- **Request timeouts**: 15-second timeout on all Hyperliquid API calls
- **Thread-safe caching**: `lru_cache` for spot metadata

## Code Quality
- **Wallet validation**: Ethereum address format validation (0x + 40 hex chars)
- **Error logging**: All exceptions logged with `logger.exception()`
- **Type hints**: Full type annotations on public functions
- **Constants**: Enums for Direction, Action, MarketType, ApiType; ErrorMsg class
- **Session management**: Context manager with auto-rollback and cleanup
- **Background sync**: APScheduler for periodic trade syncing (configurable interval)

## Database Indexes
- `idx_wallet_timestamp` - Composite index on (wallet_address, timestamp)
- `idx_wallet_asset` - Composite index on (wallet_address, asset)
- Individual index on `wallet_address`
- Individual index on `asset`

## Data Structures

### Trade Object (from Hyperliquid API)
```python
{
    "id": str,              # Unique trade ID (tid from API)
    "asset": str,           # e.g., "BTC", "ETH", "@107" (spot)
    "direction": str,       # "long" | "short" (Direction enum)
    "action": str,          # "open" | "close" (Action enum)
    "price": float,         # Execution price
    "size": float,          # Position size
    "pnl": float,           # Realized P&L (closedPnl from API)
    "fee": float,           # Trading fee
    "timestamp": int,       # Unix timestamp in milliseconds
    "notes": str            # User notes
}
```

### Round Trip Object (computed)
```python
{
    "id": str,              # "rt_{exit_fill_id}"
    "asset": str,           # Trading pair
    "display_name": str,    # Human-readable name (e.g., "HYPE/USDC")
    "market_type": str,     # "spot" | "perp" (MarketType enum)
    "direction": str,       # "long" | "short"
    "entry_price": float,   # Weighted average entry
    "exit_price": float,    # Exit price
    "size": float,          # Total position size
    "pnl": float,           # Realized P&L
    "fees": float,          # Total fees (entry + exit)
    "entry_time": int,      # First entry timestamp
    "exit_time": int,       # Exit timestamp
    "duration_ms": int,     # Trade duration
    "entry_fill_ids": list, # List of entry trade IDs
    "exit_fill_id": str,    # Exit trade ID
    "notes": str            # Combined notes from all fills
}
```

### Position Object (from Hyperliquid API)
```python
{
    "asset": str,           # Trading pair
    "size": float,          # Absolute position size
    "direction": str,       # "long" | "short"
    "entry_price": float,   # Average entry price
    "current_price": float, # Current market price
    "unrealized_pnl": float,# Unrealized P&L
    "leverage": float,      # Position leverage
    "liquidation_price": float | None,
    "margin_used": float,
    "position_value": float,
    "take_profit": float | None,
    "stop_loss": float | None
}
```

## Performance Benchmarks

### Target Metrics
| Operation | Target | Notes |
|-----------|--------|-------|
| `/api/init` | <500ms | Cached round-trips |
| `/api/positions` | <1s | 3 parallel API calls |
| `/api/trades/sync` | <3s | Depends on trade count |
| DB query (by wallet) | <50ms | With indexes |
| Round-trip computation | <100ms | For <1000 trades |

### Bottlenecks to Monitor
- Hyperliquid API latency (typically 200-500ms per call)
- Round-trip computation for wallets with >5000 trades
- PostgreSQL connection pool exhaustion under load

### Profiling Tips
```python
# Add timing to endpoints
import time
start = time.perf_counter()
# ... operation
logger.info("Operation took %.3fs", time.perf_counter() - start)
```

## Debugging Tips

### Common Issues
1. **"Invalid wallet address format"** - Ensure wallet is 0x + 40 hex chars
2. **Timeout errors** - Check Hyperliquid API status, increase REQUEST_TIMEOUT
3. **Empty round-trips** - Verify trades have both "open" and "close" actions
4. **Cache staleness** - Call `invalidate_round_trip_cache(wallet)` after manual DB changes
5. **Site unresponsive for ~5 minutes** - Usually Railway cold start or scheduler conflict; fixed with single worker + health check
6. **Mobile freezing** - Check if too many background syncs registered; disable unused ones

### Debug Logging
```bash
# Enable debug logging
export FLASK_ENV=development
export LOG_LEVEL=DEBUG
python app.py
```

### Database Inspection
```sql
-- Check trade count by wallet
SELECT wallet_address, COUNT(*) FROM trades GROUP BY wallet_address;

-- Find orphaned opens (no matching close)
SELECT asset, direction, COUNT(*)
FROM trades
WHERE action = 'open'
GROUP BY asset, direction;
```

### Scheduler Debugging
```python
from scheduler import get_scheduler
scheduler = get_scheduler()
print(scheduler.get_jobs())  # List all scheduled jobs
```

## Future Improvements
- [ ] Rate limiting on API endpoints
- [ ] WebSocket for real-time position updates
- [ ] Trade analytics dashboard (Sharpe ratio, drawdown)
- [ ] Export trades to CSV
- [ ] Telegram/Discord notifications for large P&L

## Notes
- Wallet address saved to browser localStorage for convenience
- Desktop: hover to expand trade cards, catgirls on sides
- Mobile: tap to toggle trade cards, animated Chocola gif at top
- Date filters have From/To labels for clarity
- Manual "Sync" button always syncs (bypasses cooldown)
- Code reviewed Jan 2026: clean structure, proper error handling, no security issues
- Jan 2026: Fixed mobile unresponsiveness (APScheduler + Gunicorn conflict, added health checks)
