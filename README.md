# Steam Market GUI — CS2 Skin Price Trackers

A slick desktop GUI that tracks **two CS2 items** on the Steam Community Market using the (undocumented) `priceoverview` endpoint, displays:
- Item image (fetched via the listing page OpenGraph `og:image` tag)
- Item name
- Median price & lowest price
- Live-updating chart of **your locally logged price data**

If Steam blocks the price history endpoint, this app **logs median prices** at intervals and renders a time series chart from the local CSVs.

> ⚠️ This project uses community endpoints that are undocumented by Valve and may change or be rate-limited. Use responsibly.

## Features
- Two side-by-side trackers (defaulted to your links)
- Auto-fetch every `REFRESH_SECONDS` (configurable via `.env`)
- Local CSV logging per-item in `data/`
- Pretty UI with `ttkbootstrap`
- Cross-platform start scripts

## Quick Start

### 1) Python & venv
- Python 3.10+ recommended

```bash
# macOS / Linux
./scripts/setup.sh
./scripts/start.sh
```

```bat
:: Windows
scripts\setup.bat
scripts\start.bat
```

### 2) Configure (optional)
Copy `.env.example` to `.env` and tweak:
- `REFRESH_SECONDS` (default 300)
- `CURRENCY` numeric Steam currency code (default 1 = USD)
- `ITEM_URL_1`, `ITEM_URL_2` (Steam Market listing URLs)

### 3) Run
The GUI launches and begins fetching + logging. Hover over images or titles for tooltips.

## How it works
- **Price**: `https://steamcommunity.com/market/priceoverview?appid=730&currency={{CURRENCY}}&market_hash_name={{NAME}}`
- **Image**: Scrapes the listing page `og:image` meta tag.
- **Logging**: Appends `timestamp_iso,epoch_s,median_price,lowest_price,volume` to `data/{{slug}}.csv`.
- **Plotting**: Uses Matplotlib to render a line chart of logged median prices.

## Known Limits
- The official Steam Web API does **not** provide a full Market API. These endpoints can change or require cookies.
- Heavy polling can trigger temporary rate-limits. Increase `REFRESH_SECONDS` if you see issues.
- `pricehistory` often requires being logged in in a browser session; this app does not rely on it.

## Project Layout
```
steam_market_gui/
├─ steam_market_gui/
│  ├─ __init__.py
│  ├─ gui.py
│  ├─ steam_api.py
│  ├─ data_logger.py
│  ├─ utils.py
├─ assets/
│  └─ (cached images go here)
├─ data/
│  └─ (price logs appear here)
├─ scripts/
│  ├─ setup.sh
│  ├─ start.sh
│  ├─ setup.bat
│  ├─ start.bat
├─ .env.example
├─ requirements.txt
├─ README.md
```

## Legal
This project is for educational purposes. Respect Steam's Terms of Service and do not abuse endpoints.
