"""pipeline_v2/mcp_server/tools/scrape_yc_algolia_v2.py

Queries the YCCompany_production Algolia index for recent AI-focused companies.
Isolated _v2 copy of tools/scrape_yc_algolia.py for the MCP server boundary.

Credentials are extracted dynamically from YC's public JS bundle (search-only key).
Falls back gracefully to an empty list if extraction fails.
"""

import json
import logging
import os
import re
from typing import Optional

import httpx

from pipeline_v2.mcp_server.tools.filters_v2 import has_ai_signal, is_excluded

logger = logging.getLogger(__name__)

_YC_COMPANIES_URL = "https://www.ycombinator.com/companies"
_INDEX_NAME = "YCCompany_production"
_TARGET_BATCHES = ["W25", "S25", "W24", "S24", "W23", "S23"]

_CREDS: Optional[dict] = None


def _extract_algolia_creds() -> Optional[dict]:
    global _CREDS
    if _CREDS:
        return _CREDS

    app_id = os.getenv("YC_ALGOLIA_APP_ID", "")
    api_key = os.getenv("YC_ALGOLIA_API_KEY", "")
    if app_id and api_key:
        _CREDS = {"app_id": app_id, "api_key": api_key}
        return _CREDS

    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(_YC_COMPANIES_URL)
            resp.raise_for_status()
            html = resp.text

        chunks = re.findall(r'/_next/static/chunks/[^\s"\']+\.js', html)
        for chunk_url in chunks[:20]:
            try:
                chunk_resp = httpx.get(
                    f"https://www.ycombinator.com{chunk_url}", timeout=10
                )
                text = chunk_resp.text
                id_match = re.search(r'algoliaApplicationID["\s:]+(["\`])([A-Z0-9]{10})\1', text)
                key_match = re.search(r'algoliaAPIKey["\s:]+(["\`])([a-f0-9]{32})\1', text)
                if not id_match:
                    id_match = re.search(r'"appId"\s*:\s*"([A-Z0-9]{8,12})"', text)
                if not key_match:
                    key_match = re.search(r'"apiKey"\s*:\s*"([a-f0-9]{32})"', text)
                if id_match and key_match:
                    _CREDS = {
                        "app_id": id_match.group(2) if id_match.lastindex == 2 else id_match.group(1),
                        "api_key": key_match.group(2) if key_match.lastindex == 2 else key_match.group(1),
                    }
                    logger.info("Extracted YC Algolia creds: app_id=%s", _CREDS["app_id"])
                    return _CREDS
            except Exception:
                continue
    except Exception as exc:
        logger.warning("Failed to extract YC Algolia creds: %s", exc)

    return None


def _query_yc_algolia(creds: dict, batch: str, hits_per_page: int = 200) -> list[dict]:
    url = f"https://{creds['app_id']}-dsn.algolia.net/1/indexes/{_INDEX_NAME}/query"
    headers = {
        "Content-Type": "application/json",
        "X-Algolia-Application-Id": creds["app_id"],
        "X-Algolia-API-Key": creds["api_key"],
    }
    body = {
        "hitsPerPage": hits_per_page,
        "page": 0,
        "facetFilters": [[f"batch:{batch}"]],
        "attributesToRetrieve": [
            "name", "slug", "one_liner", "long_description",
            "website", "batch", "tags", "industries",
            "team_size", "location", "country", "status",
            "top_company", "isHiring",
        ],
    }
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=15)
        resp.raise_for_status()
        return resp.json().get("hits", [])
    except Exception as exc:
        logger.warning("YC Algolia query failed for batch %s: %s", batch, exc)
        return []


def scrape_yc_algolia(batches: Optional[list[str]] = None) -> list[dict]:
    """Query YCCompany_production and return AI-focused companies.

    Returns list of dicts with keys: name, website, source, sector, stage,
    batch, team_size, location, description, tags, funding_amount,
    funding_date, tech_stack_signals, is_hiring, top_company.
    """
    creds = _extract_algolia_creds()
    if not creds:
        logger.warning("YC Algolia creds unavailable — returning empty list")
        return []

    target_batches = batches or _TARGET_BATCHES
    companies: list[dict] = []
    seen: set[str] = set()

    for batch in target_batches:
        hits = _query_yc_algolia(creds, batch)
        for hit in hits:
            name = (hit.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue

            desc = hit.get("one_liner") or hit.get("long_description") or ""
            tags = hit.get("tags") or hit.get("industries") or []
            tag_str = " ".join(tags)
            combined = f"{name} {desc} {tag_str}"

            if is_excluded(combined) or not has_ai_signal(combined):
                continue

            seen.add(name.lower())
            companies.append({
                "name": name,
                "website": hit.get("website") or "",
                "source": "yc",
                "sector": "ai-ml-infra",
                "stage": "seed",
                "batch": hit.get("batch") or batch,
                "team_size": hit.get("team_size"),
                "location": hit.get("location") or hit.get("country") or "US",
                "description": desc,
                "tags": tags,
                "funding_amount": None,
                "funding_date": hit.get("batch") or batch,
                "tech_stack_signals": "",
                "is_hiring": hit.get("isHiring", False),
                "top_company": hit.get("top_company", False),
            })

    logger.info("YC Algolia: found %d AI companies across %s", len(companies), target_batches)
    return companies
