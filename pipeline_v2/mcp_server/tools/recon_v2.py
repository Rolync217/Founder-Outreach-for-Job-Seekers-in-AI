"""pipeline_v2/mcp_server/tools/recon_v2.py

Pre-scrape site analysis — detects backend, pagination, JS framework, links.
Isolated _v2 copy of tools/recon.py for the MCP server boundary.
"""

import json
import logging
import re
from collections import Counter
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

logger = logging.getLogger(__name__)

_BLOCKED = {403, 401, 429, 503}
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def _fetch(url: str):
    """Two-tier fetch: plain requests → curl_cffi.

    Returns (html, http_status, fetch_method, tier_statuses).
    html is None if both tiers failed.
    """
    tier_statuses: dict = {}

    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        tier_statuses["requests"] = r.status_code
        if r.status_code not in _BLOCKED and len(r.text) >= 500:
            return r.text, r.status_code, "requests", tier_statuses
    except Exception as e:
        tier_statuses["requests"] = f"error: {e}"

    if _HAS_CURL_CFFI:
        try:
            r2 = cffi_requests.get(url, impersonate="chrome120", timeout=10)
            tier_statuses["curl_cffi"] = r2.status_code
            if r2.status_code not in _BLOCKED and len(r2.text) >= 500:
                return r2.text, r2.status_code, "curl_cffi", tier_statuses
        except Exception as e:
            tier_statuses["curl_cffi"] = f"error: {e}"

    last_status = next(
        (v for v in reversed(list(tier_statuses.values())) if isinstance(v, int)),
        None,
    )
    fetch_method = list(tier_statuses.keys())[-1] if tier_statuses else "requests"
    return None, last_status, fetch_method, tier_statuses


def recon(url: str) -> str:
    """Analyse a URL before scraping — returns JSON string with site metadata."""
    html, http_status, fetch_method, tier_statuses = _fetch(url)

    if html is None:
        parts = [f"{m} returned {s}" for m, s in tier_statuses.items()]
        error = ". ".join(parts) + ". Page could not be fetched without a browser."
        return json.dumps({
            "url": url,
            "http_status": http_status,
            "blocked": True,
            "fetch_method_tried": fetch_method,
            "error": error,
        }, indent=2)

    html_lower = html.lower()
    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    soup = BeautifulSoup(html, "html.parser")

    # Backend detection
    backend = "unknown"
    app_id = None
    api_key = None
    public_api_endpoint = None

    app_patterns = [
        r'"appId"\s*:\s*"([A-Z0-9]{8,})"',
        r'"app"\s*:\s*"([A-Z0-9]{8,})"',
        r'ALGOLIA_APP_ID["\s:=]+([A-Z0-9]{8,})',
        r'applicationId["\s:=]+["\']([A-Z0-9]{8,})',
    ]
    key_patterns = [
        r'"apiKey"\s*:\s*"([a-f0-9]{20,})"',
        r'"apiKey"\s*:\s*"([A-Za-z0-9+/]{20,}={0,2})"',
        r'"key"\s*:\s*"([a-f0-9]{20,})"',
        r'ALGOLIA_API_KEY["\s:=]+([a-f0-9]{20,})',
        r'searchKey["\s:=]+["\']([a-f0-9]{20,})',
    ]
    for script in soup.find_all("script"):
        script_text = script.get_text()
        if "algolia" not in script_text.lower():
            continue
        backend = "algolia"
        if not app_id:
            for p in app_patterns:
                m = re.search(p, script_text, re.IGNORECASE)
                if m:
                    app_id = m.group(1)
                    break
        if not api_key:
            for p in key_patterns:
                m = re.search(p, script_text, re.IGNORECASE)
                if m:
                    api_key = m.group(1)
                    break
        if app_id and api_key:
            break

    graphql_found = "graphql" in html_lower

    if backend == "unknown":
        api_urls = list(set(re.findall(r'https?://[^\s"\'<>]+/api/[^\s"\'<>]*', html)))
        for api_url in api_urls[:5]:
            try:
                r = requests.get(api_url, headers=_HEADERS, timeout=5)
                if r.status_code == 200:
                    public_api_endpoint = api_url
                    backend = "rest_api"
                    break
            except Exception:
                continue

    # Pagination
    pagination_types = []
    if re.search(r'[?&](page|offset|p)=\d', html):
        pagination_types.append("url_params")
    if re.search(r'[?&](cursor|after|before)=', html):
        pagination_types.append("cursor_based")
    if re.search(r'IntersectionObserver|infinite[-_]scroll', html, re.IGNORECASE):
        pagination_types.append("infinite_scroll")
    if re.search(r'load[-_]?more', html, re.IGNORECASE):
        pagination_types.append("load_more_button")
    pagination = pagination_types or None

    # JS frameworks
    js_frameworks = []
    if re.search(r'__NEXT_DATA__|_next/static|next\.js', html, re.IGNORECASE):
        js_frameworks.append("Next.js")
    if re.search(r'react[-_]dom|__reactfiber|reactdom', html, re.IGNORECASE):
        js_frameworks.append("React")
    if re.search(r'vue\.js|vuex|__vue__', html, re.IGNORECASE):
        js_frameworks.append("Vue")
    if re.search(r'ng-version|ng-app|angular\.js', html, re.IGNORECASE):
        js_frameworks.append("Angular")
    if re.search(r'__nuxt|nuxt\.js', html, re.IGNORECASE):
        js_frameworks.append("Nuxt")

    # Links
    links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        text = tag.get_text(strip=True)
        if href and not href.startswith("#") and len(text) > 1:
            links.append({"text": text, "href": href})
    links = links[:100]

    # Deep link patterns
    path_prefixes = []
    for link in links:
        href = link["href"]
        if href.startswith("/"):
            parts = href.split("/")
            if len(parts) >= 3:
                path_prefixes.append("/".join(parts[:2]))
    prefix_counts = Counter(path_prefixes).most_common(3)
    deep_link_patterns = [{"pattern": p, "count": c} for p, c in prefix_counts if c >= 3]

    # Clean text
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    plain_text = soup.get_text(separator=" ", strip=True)
    word_count = len(plain_text.split())
    clean_text = plain_text[:3000]
    js_heavy = word_count < 200 or len(js_frameworks) > 0

    # Sitemap
    sitemap = None
    for sitemap_url in [
        urljoin(base_url, "/sitemap.xml"),
        urljoin(base_url, "/sitemap_index.xml"),
    ]:
        try:
            r = requests.get(sitemap_url, headers=_HEADERS, timeout=5)
            if r.status_code == 200 and "<urlset" in r.text.lower():
                url_count = len(re.findall(r'<url>', r.text))
                sitemap = {"url": sitemap_url, "url_count": url_count}
                break
        except Exception:
            continue

    # robots.txt
    robots = None
    try:
        r = requests.get(urljoin(base_url, "/robots.txt"), headers=_HEADERS, timeout=5)
        if r.status_code == 200:
            disallowed = re.findall(r'Disallow:\s*(.+)', r.text)
            sitemap_in_robots = re.findall(r'Sitemap:\s*(.+)', r.text)
            robots = {
                "found": True,
                "disallowed_paths": [d.strip() for d in disallowed[:10]],
                "sitemap_declared": [s.strip() for s in sitemap_in_robots],
            }
            if not sitemap and sitemap_in_robots:
                try:
                    sr = requests.get(sitemap_in_robots[0].strip(), headers=_HEADERS, timeout=5)
                    if sr.status_code == 200:
                        url_count = len(re.findall(r'<url>', sr.text))
                        sitemap = {"url": sitemap_in_robots[0].strip(), "url_count": url_count}
                except Exception:
                    pass
    except Exception:
        robots = {"found": False}

    return json.dumps({
        "url": url,
        "http_status": http_status,
        "blocked": False,
        "fetch_method": fetch_method,
        "backend": backend,
        "app_id": app_id,
        "api_key": api_key,
        "graphql_detected": graphql_found,
        "public_api_endpoint": public_api_endpoint,
        "pagination": pagination,
        "js_frameworks": js_frameworks or None,
        "js_heavy": js_heavy,
        "visible_word_count": word_count,
        "has_individual_pages": len(deep_link_patterns) > 0,
        "deep_link_patterns": deep_link_patterns or None,
        "sitemap": sitemap,
        "robots": robots,
        "clean_text": clean_text,
        "links": links,
        "error": None,
    }, indent=2)
