# Hyperliquid Trade Journal

A sleek trading journal for tracking your Hyperliquid perpetual futures trades.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- **Trade Sync** - Automatically fetch trades from Hyperliquid API
- **Portfolio Stats** - P&L, fees, funding, win rate, best streak
- **Open Positions** - Real-time position tracking
- **P&L Chart** - Cumulative performance visualization
- **Trade History** - Filter by date, asset, winners/losers
- **Notes** - Add reflections to individual trades

## Quick Start

```bash
# Clone
git clone https://github.com/swin0420/hyperliquid-journal.git
cd hyperliquid-journal

# Install
pip install -r requirements.txt

# Run
python app.py
```

Open [http://localhost:5001](http://localhost:5001)

## Deployment

Deploy to Railway in one click:

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template)

Or manually:
1. Fork this repo
2. Connect to [Railway](https://railway.app)
3. Deploy from GitHub

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask |
| Frontend | Vanilla JS |
| Styling | CSS3 (Aurora theme) |
| Fonts | Inter, JetBrains Mono |
| API | Hyperliquid |

## Configuration

Set your wallet address in the UI or via environment variable:

```bash
export WALLET_ADDRESS=0xYourWalletAddress
```

## License

[MIT](LICENSE)
