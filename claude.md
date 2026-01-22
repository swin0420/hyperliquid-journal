# Hyperliquid Trade Journal

## Overview
A trading journal web app for tracking Hyperliquid perpetual futures trades with an anime-styled UI featuring Nekopara catgirls (Chocola & Vanilla).

## Tech Stack
- **Backend**: Python Flask
- **Frontend**: Vanilla JS, HTML, CSS
- **Styling**: Aurora/Northern Lights animated background, glassmorphism cards
- **Fonts**: Inter (UI), JetBrains Mono (numbers)
- **Deployment**: Railway (from GitHub)

## Project Structure
```
trade-journal/
├── app.py              # Flask routes and API endpoints
├── config.py           # Configuration (wallet address)
├── hyperliquid.py      # Hyperliquid API integration
├── storage.py          # JSON file storage for trades
├── requirements.txt    # Python dependencies
├── Procfile            # Railway deployment config
├── templates/
│   └── index.html      # Main page template
└── static/
    ├── style.css       # Styles with Aurora background
    ├── app.js          # Frontend JavaScript
    ├── catgirl-left.png   # Chocola (brown hair)
    └── catgirl-right.png  # Vanilla (white hair)
```

## Key Features
- Sync trades from Hyperliquid API by wallet address
- Track P&L, fees, funding, win rate, best win streak
- Open positions display
- Cumulative P&L chart
- Period comparison (this month vs last month)
- Trade filtering (by date, asset, P&L)
- Trade notes

## API Endpoints
- `GET /` - Main journal page
- `GET /api/trades` - Get all trades
- `POST /api/trades/sync` - Sync trades from Hyperliquid
- `GET /api/positions` - Get open positions
- `GET /api/funding` - Get funding history
- `PUT /api/trades/<id>/notes` - Update trade notes

## UI Features
- Aurora animated background (purple, pink, green, cyan gradients)
- Floating catgirl decorations with hover animations
- Responsive design (catgirls hide on smaller screens)
- Dark theme with glassmorphism cards

## Running Locally
```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5001
```

## Deployment
Deployed on Railway via GitHub integration.
Repository: https://github.com/swin0420/hyperliquid-journal
