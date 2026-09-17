"""
Data Integration Layer
-----------------------
One wrapper function per external source (IMD, INCOIS, MOSDAC, GIS).
Each checks a local SQLite cache first before hitting the real endpoint.

IMD: Real, free, no-key public JSON API. Endpoints below are correct as
of the IMD API reference (https://api.imd.gov.in/public/api_reference.html).
You DO need the right numeric/code `id` for your target sea area, coast,
or port - IMD's IDs aren't plain city names. See LOCATION_ID_MAP below;
you'll need to fill in the correct ids for the regions you care about by
checking IMD's visualize pages (e.g. https://mausam.imd.gov.in/responsive/
marine_forecast.php) and reading the id parameter from the network request
that page makes in your browser's dev tools (F12 -> Network tab).

INCOIS: No clean JSON API for PFZ advisories - they're published as
text/HTML bulletins. This uses a basic scraper as a starting point;
you'll likely need to adjust the parsing once you inspect the actual
page structure for your region.

MOSDAC: Mostly per-product download links, some requiring a free account.
Left as a placeholder - practically, INCOIS's PFZ bulletin is the more
usable ocean-conditions source for this kind of assistant.
"""

import sqlite3
import json
import time
import requests

DB_PATH = "orca_cache.db"
CACHE_TTL_SECONDS = 60 * 30  # 30 minutes - tune as needed

# Fill these in with real IMD ids for the regions you care about.
# Find them by opening https://mausam.imd.gov.in/responsive/marine_forecast.php
# (or coastal_forecast.php / port-warning.php), selecting your region, and
# reading the `id` param IMD's own frontend sends (browser dev tools -> Network).
LOCATION_ID_MAP = {
    # "kochi": {"seabulletin_id": "REPLACE_ME", "coastal_id": "REPLACE_ME", "port_id": "REPLACE_ME"},
    # "chennai": {"seabulletin_id": "REPLACE_ME", "coastal_id": "REPLACE_ME", "port_id": "REPLACE_ME"},
}


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            source TEXT,
            key TEXT,
            payload TEXT,
            fetched_at REAL,
            PRIMARY KEY (source, key)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sos_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload TEXT NOT NULL,
            created_at REAL NOT NULL,
            synced INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def _get_cached(source: str, key: str):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT payload, fetched_at FROM cache WHERE source=? AND key=?",
        (source, key),
    ).fetchone()
    conn.close()
    if row:
        payload, fetched_at = row
        if time.time() - fetched_at < CACHE_TTL_SECONDS:
            return json.loads(payload)
    return None

def _get_stale_cached(source: str, key: str):
    """Return the latest cached data even if its TTL has expired."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT payload, fetched_at FROM cache WHERE source=? AND key=?",
        (source, key),
    ).fetchone()
    conn.close()

    if row:
        payload, fetched_at = row
        return {
            "data": json.loads(payload),
            "fetched_at": fetched_at,
            "stale": time.time() - fetched_at >= CACHE_TTL_SECONDS,
        }

    return None


def _set_cached(source: str, key: str, payload: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO cache (source, key, payload, fetched_at) VALUES (?, ?, ?, ?)",
        (source, key, json.dumps(payload), time.time()),
    )
    conn.commit()
    conn.close()


_init_db()


def get_imd_weather(location: str) -> dict:
    """Fetch sea area + coastal bulletin from IMD for a location."""
    cached = _get_cached("imd", location)
    if cached:
        return cached

    stale_cached = _get_stale_cached("imd", location)

    ids = LOCATION_ID_MAP.get(location.lower())
    if not ids:
        if stale_cached:
            return {
                **stale_cached["data"],
                "cache_status": "stale",
                "cached_at": stale_cached["fetched_at"],
            }

        return {
            "error": "no_id_mapped",
            "cache_status": "unavailable",
            "note": f"No IMD id configured for '{location}' yet. Add it to LOCATION_ID_MAP in data_layer.py.",
        }

    result = {}
    successful_requests = 0

    try:
        sea = requests.get(
            "https://api.imd.gov.in/api/v1/seabulletin",
            params={"id": ids.get("seabulletin_id")},
            timeout=10,
        )
        sea.raise_for_status()
        result["sea_bulletin"] = sea.json()
        successful_requests += 1
    except Exception as e:
        result["sea_bulletin_error"] = str(e)

    try:
        coastal = requests.get(
            "https://api.imd.gov.in/api/v1/coastalbulletin",
            timeout=10,
        )
        coastal.raise_for_status()
        result["coastal_bulletin"] = coastal.json()
        successful_requests += 1
    except Exception as e:
        result["coastal_bulletin_error"] = str(e)

    try:
        port = requests.get(
            "https://api.imd.gov.in/api/v1/portwarning",
            params={"id": ids.get("port_id")},
            timeout=10,
        )
        port.raise_for_status()
        result["port_warning"] = port.json()
        successful_requests += 1
    except Exception as e:
        result["port_warning_error"] = str(e)

    if successful_requests > 0:
        result["cache_status"] = "fresh"
        _set_cached("imd", location, result)
        return result

    if stale_cached:
        return {
            **stale_cached["data"],
            "cache_status": "stale",
            "cached_at": stale_cached["fetched_at"],
        }

    return {
        "error": "imd_unavailable",
        "cache_status": "unavailable",
        "note": "IMD data is unavailable and no cached data exists.",
    }


def get_incois_pfz(location: str) -> dict:
    """Scrape INCOIS's Potential Fishing Zone text bulletin."""
    cached = _get_cached("incois", location)
    if cached:
        return cached

    stale_cached = _get_stale_cached("incois", location)

    try:
        from bs4 import BeautifulSoup

        resp = requests.get(
            "https://incois.gov.in/MarineFisheries/TextDataHome",
            params={"mfid": 1, "request_locale": "en"},
            timeout=10,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        text_content = soup.get_text(separator=" ", strip=True)

        data = {
            "raw_text_snippet": text_content[:2000],
            "note": (
                "Adjust the BeautifulSoup selector to target the "
                "specific advisory table/text for your region."
            ),
            "cache_status": "fresh",
        }

        _set_cached("incois", location, data)
        return data

    except Exception as e:
        if stale_cached:
            return {
                **stale_cached["data"],
                "cache_status": "stale",
                "cached_at": stale_cached["fetched_at"],
                "source_error": str(e),
            }

        return {
            "error": "incois_unavailable",
            "cache_status": "unavailable",
            "note": "INCOIS data is unavailable and no cached data exists.",
            "source_error": str(e),
        }


def get_mosdac_eo(location: str) -> dict:
    """MOSDAC (ISRO) ocean/earth-observation products."""
    cached = _get_cached("mosdac", location)
    if cached:
        return cached

    stale_cached = _get_stale_cached("mosdac", location)

    data = {
        "note": (
            "MOSDAC does not offer a simple query API. Free products are "
            "listed at https://www.mosdac.gov.in/open-data with per-product "
            "download links; some require a free MOSDAC account."
        ),
        "cache_status": "fresh",
    }

    _set_cached("mosdac", location, data)
    return data

def get_gis_boundaries(location: str) -> dict:
    """Fetch GIS boundary/geofencing data for a location."""
    cached = _get_cached("gis", location)
    if cached:
        return cached

    stale_cached = _get_stale_cached("gis", location)

    data = {
        "note": (
            "Load boundary polygons locally via "
            "geopandas.read_file('boundaries.geojson')"
        ),
        "cache_status": "fresh",
    }

    _set_cached("gis", location, data)
    return data

def queue_sos_event(payload: dict) -> int:
    """Store an SOS event locally until it can be synced."""
    conn = sqlite3.connect(DB_PATH)

    cursor = conn.execute(
        "INSERT INTO sos_queue (payload, created_at, synced) VALUES (?, ?, 0)",
        (json.dumps(payload), time.time()),
    )

    conn.commit()
    event_id = cursor.lastrowid
    conn.close()

    return event_id

def get_unsynced_sos_events() -> list:
    """Return all SOS events waiting to be synced."""
    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute(
        "SELECT id, payload, created_at FROM sos_queue WHERE synced=0 ORDER BY id"
    ).fetchall()

    conn.close()

    return [
        {
            "id": row[0],
            "payload": json.loads(row[1]),
            "created_at": row[2],
        }
        for row in rows
    ]

def mark_sos_event_synced(event_id: int):
    """Mark an SOS event as successfully synchronized."""
    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        "UPDATE sos_queue SET synced=1 WHERE id=?",
        (event_id,),
    )

    conn.commit()
    conn.close()

def sync_sos_events(sync_url: str, timeout: int = 10) -> dict:
    """Try to send all queued SOS events to the backend."""
    pending_events = get_unsynced_sos_events()

    if not pending_events:
        return {
            "success": True,
            "synced": 0,
            "remaining": 0,
        }

    synced_count = 0

    for event in pending_events:
        try:
            response = requests.post(
                sync_url,
                json=event["payload"],
                timeout=timeout,
            )
            response.raise_for_status()

            mark_sos_event_synced(event["id"])
            synced_count += 1

        except requests.RequestException:
            # Keep the event in the queue so it can be retried later.
            break

    remaining = len(get_unsynced_sos_events())

    return {
        "success": remaining == 0,
        "synced": synced_count,
        "remaining": remaining,
    }
