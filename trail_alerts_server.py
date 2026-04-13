#!/usr/bin/env python3
# trail_alerts_server.py
#
# Custom MCP server for trail/park closure and opening alerts.
# Uses newsapi.org /v2/everything endpoint.
#
# Setup (one-time):
#   export NEWSAPI_KEY=6d079103dd174946af894e6653d91a75
#   pip3 install "mcp[cli]" httpx
#
# Run standalone:
#   python3 trail_alerts_server.py
#
# Install into Claude Code:
#   mcp install trail_alerts_server.py --name trail-alerts \
#       -e NEWSAPI_KEY=6d079103dd174946af894e6653d91a75

import os
import json
import httpx
from datetime import datetime, timedelta, timezone
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("trail-alerts")

NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "6d079103dd174946af894e6653d91a75")
BASE_URL    = "https://newsapi.org/v2/everything"

KEYWORDS = [
    "trail closed", "trail closure", "trail open", "trail reopened",
    "park closed", "park closure", "park reopened", "park open",
    "hiking trail closed", "wildfire trail closure",
    "flood trail closed", "landslide trail",
    "trail access restricted", "trailhead closed",
]


@mcp.tool()
async def search_trail_alerts(
    hours_back: int = 24,
    language: str = "en",
    max_results: int = 50,
) -> str:
    """
    Search global news for trail/park closure and opening alerts.
    Returns articles matching trail-related keywords from the last N hours.

    Args:
        hours_back:  How many hours back to search (default 24).
        language:    Two-letter language code, e.g. "en". Leave blank for all languages.
        max_results: Max articles to return (1–100).
    """
    query     = " OR ".join(f'"{kw}"' for kw in KEYWORDS)
    date_from = (
        datetime.now(timezone.utc) - timedelta(hours=hours_back)
    ).strftime("%Y-%m-%dT%H:%M:%S")

    params: dict = {
        "q":         query,
        "from":      date_from,
        "sortBy":    "publishedAt",
        "pageSize":  min(max_results, 100),
        "apiKey":    NEWSAPI_KEY,
    }
    if language:
        params["language"] = language

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "ok":
        return json.dumps({"error": data.get("message", "Unknown error")})

    results = []
    for a in data.get("articles", []):
        title  = (a.get("title") or "").strip()
        if not title or title == "[Removed]":
            continue

        # newsapi.org doesn't supply location entities — extract from text
        combined = f"{title} {a.get('description') or ''}"
        locations = _extract_locations(combined)

        results.append({
            "title":        title,
            "source":       a.get("source", {}).get("name", ""),
            "url":          a.get("url", ""),
            "date":         a.get("publishedAt", ""),
            "body_snippet": (a.get("description") or "")[:500],
            "locations":    locations,
        })

    return json.dumps({"count": len(results), "alerts": results}, indent=2)


@mcp.tool()
async def match_alerts_to_trails(
    alerts_json: str,
    trails_geojson_path: str,
) -> str:
    """
    Takes alert results (from search_trail_alerts) and a GeoJSON file of
    trails/parks, and returns matches based on name/region overlap.
    Useful for tagging specific trails with news alerts.

    Args:
        alerts_json:        JSON string returned by search_trail_alerts.
        trails_geojson_path: Absolute path to a GeoJSON file with trail features.
                             Each feature needs properties: name, region (optional), id.
    """
    alerts = json.loads(alerts_json)
    with open(trails_geojson_path) as f:
        trails = json.load(f)

    matches = []
    for alert in alerts.get("alerts", []):
        alert_locations = {loc.lower() for loc in alert.get("locations", [])}
        alert_text      = (
            (alert.get("title") or "") + " " + (alert.get("body_snippet") or "")
        ).lower()

        for feature in trails.get("features", []):
            props      = feature.get("properties", {})
            trail_name = (props.get("name") or "").lower()
            trail_region = (props.get("region") or "").lower()

            # Match on location entities OR trail/region name appearing in article text
            name_in_text   = trail_name   and trail_name   in alert_text
            region_in_text = trail_region and trail_region in alert_text
            entity_overlap = bool(alert_locations & {trail_name, trail_region})

            if name_in_text or region_in_text or entity_overlap:
                matches.append({
                    "alert_title": alert["title"],
                    "alert_url":   alert["url"],
                    "alert_date":  alert["date"],
                    "trail_id":    props.get("id"),
                    "trail_name":  props.get("name"),
                    "match_reason": (
                        "name_in_text"   if name_in_text   else
                        "region_in_text" if region_in_text else
                        "entity_overlap"
                    ),
                })

    return json.dumps({"total": len(matches), "matched_alerts": matches}, indent=2)


# ── Helpers ───────────────────────────────────────────────────────────────────

import re

US_STATES = [
    "Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut",
    "Delaware","Florida","Georgia","Hawaii","Idaho","Illinois","Indiana","Iowa",
    "Kansas","Kentucky","Louisiana","Maine","Maryland","Massachusetts","Michigan",
    "Minnesota","Mississippi","Missouri","Montana","Nebraska","Nevada",
    "New Hampshire","New Jersey","New Mexico","New York","North Carolina",
    "North Dakota","Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island",
    "South Carolina","South Dakota","Tennessee","Texas","Utah","Vermont",
    "Virginia","Washington","West Virginia","Wisconsin","Wyoming",
]

COUNTRIES = [
    "Canada","Australia","New Zealand","United Kingdom","England","Scotland",
    "Wales","Ireland","France","Spain","Germany","Italy","Japan","Brazil",
    "Mexico","Chile","New Zealand","Switzerland","Norway","Sweden",
]

_LOCATION_WORDS = US_STATES + COUNTRIES

def _extract_locations(text: str) -> list[str]:
    """Best-effort location extraction from article text."""
    found = []
    for loc in _LOCATION_WORDS:
        if re.search(r"\b" + re.escape(loc) + r"\b", text, re.I):
            found.append(loc)
    return found


if __name__ == "__main__":
    mcp.run()
