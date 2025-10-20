IT Trends MCP Server

Overview
This repository provides a Model Context Protocol (MCP) server that collects and analyzes signals about the popularity of IT services, technologies, and trends. It exposes tools via MCP to fetch Reddit discussions, aggregate metrics, and generate reports (HTML/PDF/Excel). The design is extensible to add freelance market scrapers and trend searchers (Google Trends, GitHub Trending, Stack Overflow).

Architecture
- server.py: MCP server built with FastMCP, registering tools, resources, and prompts.
- tools/
  - reddit_analyzer.py: Fetches and analyzes Reddit posts using PRAW; extracts technology mentions and naive sentiment.
  - report_generator.py: Generates HTML/PDF/Excel reports; renders charts with matplotlib.
  - freelance_analyzer.py: Placeholder for Upwork/Freelancer/Fiverr scraping (to be implemented).
  - trends_searcher.py: Placeholder for Google Trends/GitHub/StackOverflow analysis (to be implemented).
- utils/
  - cache_manager.py: File/Redis cache with TTL and get_or_fetch helpers.
  - data_processor.py: Normalization, growth rate, anomaly detection, and multi-source aggregation helpers.
  - api_clients.py: Factory for external API clients (Reddit for now).
- templates/
  - report_template.html: Jinja2 template for HTML reports.
- config.yaml: Configuration for server, data sources, analysis, cache, DB, and reporting.

MCP Components
Tools
- analyze_reddit
  - Input: subreddits: list[str], lookback_days: int, keywords: list[str]
  - Output: JSON with top_technologies (technology, mentions), sentiment per technology, and stats
  - Implementation: PRAW client, fetch recent posts from specified subs, extract keyword mentions, naive sentiment, rank by mentions

- generate_report
  - Input: data: dict, format: str (pdf/excel/html), include_charts: bool
  - Output: { "path": "..." } with path to the generated report file
  - Implementation: Jinja2 template for HTML, matplotlib chart, PDF via reportlab, Excel via openpyxl

- analyze_freelance (stub)
  - Input: platforms: list[str], categories: list[str] (optional)
  - Output: { status: "not_implemented", message: "..." }

- search_trends (stub)
  - Input: keywords: list[str], timeframe: str, region: str
  - Output: { status: "not_implemented", message: "..." }

- get_historical_comparison (stub)
  - Input: technology: str, days_back: int
  - Output: { status: "not_implemented", message: "..." }

Resources
- cache://trends/{date} – Returns cached trends by date if present.
- history://technology/{name} – Returns historical data for a technology if present (cache or ./data file).

Prompts
- analysis_prompt – System prompt for analysis.
- forecast_prompt – System prompt for forecasts.

Installation
1) Clone and prepare environment
- Python 3.10+
- Create and activate a virtual environment

2) Install dependencies
pip install -r requirements.txt

3) Configure environment
- Copy .env.example to .env and fill in values
- At minimum provide Reddit credentials:
  - REDDIT_CLIENT_ID
  - REDDIT_CLIENT_SECRET

4) Review config.yaml
- Adjust subreddits, cache backend, report output dir, etc.

Running the MCP Server
The server communicates over stdio by default.
python server.py

Available Tools (MCP)
- analyze_reddit
  - Example call
    result = await mcp_client.call_tool("analyze_reddit", {
        "subreddits": ["programming", "webdev"],
        "lookback_days": 7,
        "keywords": ["python", "javascript", "react"]
    })

- generate_report
  - Example call
    report = await mcp_client.call_tool("generate_report", {
        "data": result,
        "format": "html",  # or "pdf" / "excel"
        "include_charts": True
    })

Data Schemas
- analyze_reddit result
  {
    "date": "YYYY-MM-DD",
    "subreddits": ["..."],
    "lookback_days": 7,
    "top_technologies": [
      {"technology": "python", "mentions": 123},
      ...
    ],
    "sentiment": {
      "python": {"avg_sentiment": 0.42, "mentions": 25},
      ...
    },
    "stats": {"posts_analyzed": 300, "unique_tech_count": 20}
  }

- generate_report result
  { "path": "./reports/report_20250101_120000.html" }

Troubleshooting
- Reddit credentials missing
  - The server will gracefully return empty results if the Reddit client is not configured. Provide REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in your .env.
- SSL / network errors
  - The Reddit fetcher has simple retry with exponential backoff. Check connectivity or try again later.
- Charts not visible
  - Ensure matplotlib is installed and a non-headless backend is available. The report will still be generated without charts.
- PDF/Excel generation issues
  - If reportlab or openpyxl are missing, the server falls back to HTML generation.
- Redis cache not working
  - Verify REDIS_URL and that a Redis server is running, or switch cache.storage to "file" in config.yaml.

Roadmap
- Implement freelance_analyzer (Upwork/Freelancer/Fiverr) with rate limiting and async fetching
- Implement trends_searcher (Google Trends, GitHub, StackOverflow)
- Persist historical data and enable get_historical_comparison
- Advanced NLP sentiment analysis and language detection

License
Apache-2.0 or similar, choose as appropriate for your project.
