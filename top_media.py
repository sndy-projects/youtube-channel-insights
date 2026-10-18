"""
Top Media channel comparison.

Pulls PUBLIC stats for a set of major media YouTube channels (sports leagues,
networks, studios) with the YouTube Data API v3 and an API key, stores them in
SQLite, and runs comparison queries (upload frequency, engagement, Shorts mix).

Usage:
    export YT_API_KEY="your-api-key"
    python top_media.py fetch            # pull data into top_media.db
    python top_media.py report           # run the SQL comparisons in queries.sql

Quota: roughly 1 unit per API call. With 5 channels x 200 videos this is
~45 units per run, far below the default 10,000 units/day.
"""

import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Channels to compare. Handles can change; if one fails to resolve, look it up
# on youtube.com and update it here.
CHANNELS = [
    "@NFL",
    "@NBA",
    "@MLB",
    "@ESPN",
    "@WarnerBrosPictures",
]

MAX_VIDEOS_PER_CHANNEL = 200   # most recent uploads to analyze per channel
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "top_media.db")
QUERIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries.sql")

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id     TEXT PRIMARY KEY,
    handle         TEXT,
    title          TEXT,
    subscribers    INTEGER,          -- NULL if the channel hides it
    total_views    INTEGER,
    video_count    INTEGER,
    fetched_at     TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    video_id          TEXT PRIMARY KEY,
    channel_id        TEXT REFERENCES channels(channel_id),
    title             TEXT,
    published_at      TEXT,          -- ISO 8601 UTC, e.g. 2026-10-12T18:30:00Z
    duration_seconds  INTEGER,
    views             INTEGER,
    likes             INTEGER,       -- NULL if likes are hidden
    comments          INTEGER,       -- NULL if comments are disabled
    fetched_at        TEXT
);
"""


# ---------------------------------------------------------------- helpers

def parse_iso_duration(value):
    """Convert an ISO 8601 duration like 'PT1H2M30S' to seconds."""
    if not value:
        return None
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return None
    days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def to_int(value):
    return int(value) if value is not None else None


def call_api(request, retries=4):
    """Execute an API request with exponential backoff on transient errors.

    Stops immediately on quota errors, since retrying won't help until the
    quota resets (midnight Pacific time).
    """
    for attempt in range(retries + 1):
        try:
            return request.execute()
        except HttpError as err:
            status = err.resp.status
            reason = ""
            try:
                reason = err.error_details[0].get("reason", "")
            except (AttributeError, IndexError, TypeError):
                pass
            if status == 403 and reason in ("quotaExceeded", "dailyLimitExceeded"):
                sys.exit("Quota exceeded for today. Try again after the quota resets.")
            if status in (500, 502, 503, 504) or reason in ("rateLimitExceeded", "userRateLimitExceeded"):
                if attempt < retries:
                    wait = 2 ** attempt
                    print(f"  transient error {status} {reason}; retrying in {wait}s")
                    time.sleep(wait)
                    continue
            raise


# ---------------------------------------------------------------- fetching

def fetch_channel(youtube, handle):
    response = call_api(youtube.channels().list(
        part="snippet,statistics,contentDetails",
        forHandle=handle,
    ))
    items = response.get("items", [])
    if not items:
        print(f"  could not resolve {handle}; check the handle on youtube.com")
        return None
    return items[0]


def fetch_recent_video_ids(youtube, uploads_playlist_id, limit):
    ids, page_token = [], None
    while len(ids) < limit:
        response = call_api(youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=page_token,
        ))
        ids.extend(item["contentDetails"]["videoId"] for item in response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return ids[:limit]


def fetch_video_details(youtube, video_ids):
    videos = []
    for start in range(0, len(video_ids), 50):       # API accepts up to 50 IDs per call
        batch = video_ids[start:start + 50]
        response = call_api(youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(batch),
        ))
        videos.extend(response.get("items", []))
    return videos


def fetch_all(api_key):
    youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for handle in CHANNELS:
        print(f"Fetching {handle} ...")
        channel = fetch_channel(youtube, handle)
        if channel is None:
            continue

        stats = channel.get("statistics", {})
        channel_id = channel["id"]
        conn.execute(
            "INSERT OR REPLACE INTO channels VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                channel_id,
                handle,
                channel["snippet"]["title"],
                None if stats.get("hiddenSubscriberCount") else to_int(stats.get("subscriberCount")),
                to_int(stats.get("viewCount")),
                to_int(stats.get("videoCount")),
                now,
            ),
        )

        uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]
        video_ids = fetch_recent_video_ids(youtube, uploads, MAX_VIDEOS_PER_CHANNEL)
        videos = fetch_video_details(youtube, video_ids)

        rows = []
        for v in videos:
            s = v.get("statistics", {})
            rows.append((
                v["id"],
                channel_id,
                v["snippet"]["title"],
                v["snippet"]["publishedAt"],
                parse_iso_duration(v["contentDetails"].get("duration")),
                to_int(s.get("viewCount")),
                to_int(s.get("likeCount")),
                to_int(s.get("commentCount")),
                now,
            ))
        conn.executemany("INSERT OR REPLACE INTO videos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
        print(f"  saved {len(rows)} videos from {channel['snippet']['title']}")

    conn.close()
    print(f"Done. Data is in {DB_PATH}")


# ---------------------------------------------------------------- reporting

def run_report():
    if not os.path.exists(DB_PATH):
        sys.exit("No database yet. Run: python top_media.py fetch")
    conn = sqlite3.connect(DB_PATH)
    with open(QUERIES_PATH) as f:
        sql_text = f.read()

    # Each query in queries.sql starts with a "-- name: ..." line.
    blocks = re.split(r"^-- name: ", sql_text, flags=re.MULTILINE)[1:]
    for block in blocks:
        name, _, query = block.partition("\n")
        cursor = conn.execute(query)
        headers = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        print(f"\n=== {name.strip()} ===")
        widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(h)
                  for i, h in enumerate(headers)]
        print("  ".join(str(h).ljust(w) for h, w in zip(headers, widths)))
        for row in rows:
            print("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))
    conn.close()


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "fetch":
        key = os.environ.get("YT_API_KEY")
        if not key:
            sys.exit("Set your API key first: export YT_API_KEY=...")
        fetch_all(key)
    elif command == "report":
        run_report()
    else:
        print(__doc__)
