# Hyperliquid Trade Journal

## Overview
A multi-user trading journal web app for tracking Hyperliquid perpetual futures and spot trades. Features anime-styled UI with Nekopara catgirls (Chocola & Vanilla).

**Live Site**: https://hl-journal.xyz

## Tech Stack
- **Backend**: Python Flask, SQLAlchemy
- **Database**: PostgreSQL (Railway)
- **Frontend**: Vanilla JS, HTML, CSS, Chart.js
- **Styling**: Aurora/Northern Lights animated background, glassmorphism cards
- **Fonts**: Inter (UI), JetBrains Mono (numbers)
- **Deployment**: Railway (from GitHub)

## Project Structure
```
trade-journal/
├── app.py              # Flask routes and API endpoints
├── config.py           # Configuration (DATABASE_URL)
├── hyperliquid.py      # Hyperliquid API integration
├── storage.py          # PostgreSQL storage with SQLAlchemy
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
All endpoints require wallet address (query param, body, or header).

- `GET /` - Main journal page
- `GET /api/init?wallet=0x...` - Get roundtrips + assets (combined, faster)
- `GET /api/trades?wallet=0x...` - Get all trades
- `POST /api/trades/sync` - Sync trades from Hyperliquid
- `GET /api/roundtrips?wallet=0x...` - Get round-trip trades
- `GET /api/positions?wallet=0x...` - Get open positions with current prices
- `GET /api/funding?wallet=0x...` - Get funding history
- `GET /api/assets?wallet=0x...` - Get unique traded assets
- `PUT /api/trades/<id>/notes` - Update trade notes

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

## Environment Variables
- `DATABASE_URL` - PostgreSQL connection string (required for production)

## Performance Optimizations
- **Parallel API calls**: Hyperliquid API calls (clearinghouseState, allMids, openOrders) run concurrently
- **Sync cooldown**: Auto-sync skipped if synced within 30 seconds (per-wallet)
- **Combined endpoint**: `/api/init` returns roundtrips + assets in single request
- **Image preloading**: Desktop catgirl images preloaded for faster display

## Notes
- Wallet address saved to browser localStorage for convenience
- Desktop: hover to expand trade cards, catgirls on sides
- Mobile: tap to toggle trade cards, animated Chocola gif at top
- Date filters have From/To labels for clarity
- Manual "Sync" button always syncs (bypasses cooldown)
- Code reviewed Jan 2026: clean structure, proper error handling, no security issues
