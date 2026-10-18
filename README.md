# YouTube Channel Insights

A Python app that uses the YouTube Data API v3 to pull and analyze channel and video metrics.

## Features
- **Top Media comparison** (`top_media.py`): pulls public stats for major sports and entertainment channels (NFL, NBA, MLB, ESPN, Warner Bros. Pictures) with an API key, stores them in SQLite and compares upload frequency, engagement rate, Shorts vs. long-form mix and posting patterns with SQL (`queries.sql`).
- **My channel analytics** (in progress): OAuth 2.0 sign-in with Google to pull private analytics for an authorized channel.

## Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run the Top Media comparison
```bash
export YT_API_KEY="your-api-key"
python top_media.py fetch
python top_media.py report
```

## Notes
- Shorts are approximated as videos of 3 minutes or less, since the API does not flag Shorts directly.
- Quota-aware: about 45 API units per run against the default 10,000 units/day. Quota errors stop the run; transient server errors retry with exponential backoff.

## Troubleshooting log
_Issues hit while building this and how they were fixed._
