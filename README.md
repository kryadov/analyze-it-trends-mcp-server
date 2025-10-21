# IT Trends MCP Server

## Overview
This repository provides a Model Context Protocol (MCP) server that collects and analyzes signals about the popularity of IT services, technologies, and trends. It exposes tools via MCP to fetch Reddit discussions, aggregate metrics, and generate reports (HTML/PDF/Excel). The design is extensible to add freelance market scrapers and trend searchers (Google Trends, GitHub Trending, Stack Overflow).

## Architecture
- `server.py`: MCP server built with FastMCP, registering tools, resources, and prompts.
- `tools/`
  - `reddit_analyzer.py`: Fetches and analyzes Reddit posts using PRAW; extracts technology mentions and naive sentiment.
  - `report_generator.py`: Generates HTML/PDF/Excel reports; renders charts with matplotlib.
  - `freelance_analyzer.py`: Scrapes and parses public freelance markets (Upwork/Freelancer) and aggregates skills demand with basic rate analysis.
  - `trends_searcher.py`: Searches public signals from Google Trends, GitHub Trending, and Stack Overflow tags; normalizes and aggregates results.
- `utils/`
  - `cache_manager.py`: File/Redis cache with TTL and get_or_fetch helpers.
  - `data_processor.py`: Normalization, growth rate, anomaly detection, and multi-source aggregation helpers.
  - `api_clients.py`: Factory for external API clients (Reddit for now).
- `templates/`
  - `report_template.html`: Jinja2 template for HTML reports.
- `config.yaml`: Configuration for server, data sources, analysis, cache, DB, and reporting.

## MCP Components

### Tools
- `analyze_trends` (aliases: `analyze`, `trends_analyze`)
  - Input: `days: int = 7`, `sources: {"reddit": bool, "freelance": bool, "trends": bool}`, `include_charts: bool`, `language: str`
  - Output: `{ "date": "YYYY-MM-DD", "top_trends": list[str], "growth_leaders": list[str], "sources": {..}, "summary": str }`
  - Notes: Aggregates public signals (Google Trends, GitHub Trending, Stack Overflow) with daily caching.

- `search_trends`
  - Input: `keywords: list[str]`, `timeframe: str = "now 7-d"`, `region: str = "US"`
  - Output: `{ "date": "YYYY-MM-DD", "inputs": {..}, "sources": { "google_trends": {...}, "github_trending": {...}, "stackoverflow": {...} }, "top_technologies": [{"technology": str, "mentions": float}] }`

- `analyze_reddit`
  - Input: `subreddits: list[str]`, `lookback_days: int`, `keywords: list[str]`
  - Output: JSON with `top_technologies` (technology, mentions), sentiment per technology, and stats
  - Implementation: PRAW client, fetch recent posts from specified subs, extract keyword mentions, naive sentiment, rank by mentions

- `analyze_freelance`
  - Input: `platforms: list[str]` (one or more of: upwork, freelancer, all), `categories: list[str]` (optional)
  - Output: `{ "date": "YYYY-MM-DD", "source": "freelance_markets", "platforms": [...], "top_technologies": [...], "avg_hourly_rate": number, "stats": {...}, "status": "ok|partial|not_available" }`

- `generate_report` (aliases: `report_generate`, `create_report`)
  - Input: `data: dict`, `format: str` (pdf/excel/html), `include_charts: bool`
  - Output: `{ "file_path": "...", "path": "..." }` with path to the generated report file
  - Implementation: Jinja2 template for HTML, matplotlib charts, PDF via reportlab, Excel via openpyxl

- `get_historical_comparison` (stub)
  - Input: `technology: str`, `days_back: int`
  - Output: `{ status: "not_implemented", message: "..." }`

### Resources
- `cache://trends/{date}` – Returns cached trends by date if present.
- `history://technology/{name}` – Returns historical data for a technology if present (cache or `./data` file).

### Prompts
- `analysis_prompt` – System prompt for analysis.
- `forecast_prompt` – System prompt for forecasts.

## Installation
1. Clone and prepare environment
   - Python 3.10+
   - Create and activate a virtual environment
   ```shell
    python -m venv .venv
    ```
2. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment
   - Create a `.env` file in the project root and set the required variables.
   - At minimum provide Reddit credentials:
     - `REDDIT_CLIENT_ID`
     - `REDDIT_CLIENT_SECRET`
   - Optional: `GITHUB_TOKEN`, `STACKOVERFLOW_KEY`, `REDIS_URL`
4. Review `config.yaml`
   - Adjust subreddits, cache backend, report output dir, etc.

## Running the MCP Server
By default, `server.py` runs the Streamable HTTP transport (configured via `config.yaml`, default http://localhost:8080/).

You can also use the helper scripts:
- Windows: `run_server.bat`
- macOS/Linux: `./run_server.sh`

To run directly:
```bash
python server.py
```

## Available Tools (MCP)
- `analyze_trends` (aliases: `analyze`, `trends_analyze`)
  - Example call
    ```text
    result = await mcp_client.call_tool("analyze_trends", {
        "days": 7,
        "sources": {"reddit": true, "freelance": true, "trends": true},
        "include_charts": true,
        "language": "en"
    })
    ```

- `analyze_reddit`
  - Example call
    ```text
    result = await mcp_client.call_tool("analyze_reddit", {
        "subreddits": ["programming", "webdev"],
        "lookback_days": 7,
        "keywords": ["python", "javascript", "react"]
    })
    ```

- `generate_report` (aliases: `report_generate`, `create_report`)
  - Example call
    ```text
    report = await mcp_client.call_tool("generate_report", {
        "data": result,
        "format": "html",  # or "pdf" / "excel"
        "include_charts": true
    })
    # Note: Response includes both keys: {"file_path": "...", "path": "..."}
    ```

## Data Schemas
### analyze_trends result
```json
{
  "date": "YYYY-MM-DD",
  "top_trends": ["python", "rust", "kotlin"],
  "growth_leaders": ["langchain", "webgpu", "bun"],
  "sources": {"reddit": true, "freelance": true, "trends": true},
  "summary": "Aggregated technology signals from public sources for the last N days."
}
```

### analyze_reddit result
```json
{
  "date": "YYYY-MM-DD",
  "subreddits": ["programming", "webdev"],
  "lookback_days": 7,
  "top_technologies": [
    {"technology": "python", "mentions": 123},
    {"technology": "javascript", "mentions": 98}
  ],
  "sentiment": {
    "python": {"avg_sentiment": 0.42, "mentions": 25},
    "javascript": {"avg_sentiment": 0.12, "mentions": 30}
  },
  "stats": {"posts_analyzed": 300, "unique_tech_count": 20}
}
```

### generate_report result
```json
{ "file_path": "./reports/report_20250101_120000.html", "path": "./reports/report_20250101_120000.html" }
```

## Troubleshooting
- Reddit credentials missing
  - The server will gracefully return empty results if the Reddit client is not configured. Provide `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` in your `.env`.
- SSL / network errors
  - The Reddit fetcher has simple retry with exponential backoff. Check connectivity or try again later.
- Charts not visible
  - Ensure `matplotlib` is installed and a non-headless backend is available. The report will still be generated without charts.
- PDF/Excel generation issues
  - If `reportlab` or `openpyxl` are missing, the server falls back to HTML generation.
- Redis cache not working
  - Verify `REDIS_URL` and that a Redis server is running, or switch `cache.storage` to "file" in `config.yaml`.

## Getting Reddit API credentials
Follow these steps to create a Reddit app and obtain the credentials required by this project:

1. Sign in to Reddit with your account.
2. Go to https://www.reddit.com/prefs/apps (or https://old.reddit.com/prefs/apps).
3. Click "create app" (or "create another app").
4. Fill in the form:
   - Name: e.g., IT Trends MCP
   - App type: script
   - Description: optional
   - Redirect URI: http://localhost:8080 (required by Reddit; not used by this project)
5. After the app is created, copy:
   - Client ID: the short string shown under the app name (next to "personal use script").
   - Client Secret: the value labeled "secret".
6. Put them into your .env:
   - REDDIT_CLIENT_ID=your_client_id
   - REDDIT_CLIENT_SECRET=your_client_secret
   - REDDIT_USER_AGENT=ITTrendsAnalyzer/1.0 by <your_reddit_username>
7. Save the .env and restart the server.

Notes:
- The server uses read-only access via PRAW; no username/password or refresh tokens are needed.
- Use a unique, descriptive user agent per Reddit API rules.
- API usage is rate-limited; if you hit errors, slow down and try again later.

## Roadmap
- Persist historical data and enable `get_historical_comparison`
- Add more freelance sources (e.g., Fiverr) and richer rate analytics
- OAuth/API integrations for GitHub/StackExchange where appropriate
- Forecasting improvements using time-series models
- Add tests and CI; provide Docker packaging

## License
Apache-2.0 or similar, choose as appropriate for your project.
