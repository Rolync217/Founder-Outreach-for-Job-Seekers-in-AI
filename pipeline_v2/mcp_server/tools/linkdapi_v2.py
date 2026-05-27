"""pipeline_v2/mcp_server/tools/linkdapi_v2.py

LinkedIn data tool via LinkdAPI.

Public functions:
    resolve_founder_linkedin(name, company_name, existing_url=None) -> str | None
    resolve_company_linkedin(company_name, existing_id=None) -> str | None
    get_hiring_signals(founder_linkedin_url, company_linkedin_id, lookback_days, company_name) -> HiringSignalResult

Add LINKDAPI_KEY to .env before use.
Optional: LINKDAPI_BASE_URL (default: https://api.linkdapi.com/v1 — verify on first real call).
"""

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = os.getenv("LINKDAPI_BASE_URL", "https://api.linkdapi.com/v1")

_DIRECT_PATTERNS = re.compile(
    r"we'?re hiring|we are hiring|join our team|join us\b|"
    r"looking for a\b|open role|open position|applications open|now hiring|"
    r"dm me if|link in bio|check our careers|founding engineer|"
    r"full.?stack engineer|looking for engineers?|"
    r"we'?re looking for|seeking a\b|seeking an\b|"
    r"apply (?:now|here|at)\b|apply via|(?:role|roles|position)s? at\b",
    re.IGNORECASE,
)

_INDIRECT_PATTERNS = re.compile(
    r"we raised|just closed|seed round|series [abc]\b|"
    r"we'?re growing|growing the team|expanding our team|new chapter|"
    r"backed by|thrilled to announce|just announced|"
    r"excited to share|new hire\b|new team member|"
    r"welcome(?:ing)?.*?(?:team|aboard)|joined.*?team|grew our team",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class HiringSignalResult:
    tier: str                               # "direct" | "indirect" | "none"
    confidence: str                         # "high" | "medium" | "low"
    signals: list[str] = field(default_factory=list)
    evidence_posts: list[dict] = field(default_factory=list)
    is_hiring_flag: Optional[bool] = None
    founder_url_resolved: Optional[str] = None
    company_id_resolved: Optional[str] = None
    credits_used: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _headers() -> dict:
    key = os.getenv("LINKDAPI_KEY")
    if not key:
        raise RuntimeError("LINKDAPI_KEY not set in environment")
    return {"X-AUTHAPI-Key": key}


def _get(path: str, params: Optional[dict] = None, retries: int = 3) -> dict:
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    wait = 10
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=15)
            if resp.status_code == 429:
                logger.warning("LinkdAPI rate limit, sleeping %ss", wait)
                time.sleep(wait)
                wait = min(wait * 2, 120)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise
            logger.warning("LinkdAPI request failed (attempt %d): %s", attempt + 1, exc)
            time.sleep(wait)
            wait = min(wait * 2, 120)
    return {}


def _username_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    m = re.search(r"linkedin\.com/in/([^/?#\s]+)", url)
    return m.group(1).rstrip("/") if m else None


def _urn_from_username(username: str) -> tuple[Optional[str], int]:
    try:
        data = _get("username-to-urn", {"username": username})
        urn = data.get("data", {}).get("urn") or data.get("urn")
        return urn, 1
    except Exception as exc:
        logger.warning("username-to-urn failed for %s: %s", username, exc)
        return None, 1


def _profile_full(username: str) -> tuple[dict, int]:
    try:
        data = _get("profile/full", {"username": username})
        return data.get("data", {}), 1
    except Exception as exc:
        logger.warning("profile/full failed for %s: %s", username, exc)
        return {}, 1


def _search_posts(
    urn: str,
    keyword: Optional[str] = None,
    date_posted: str = "past-year",
    sort_by: str = "date_posted",
) -> tuple[list[dict], int]:
    params: dict = {"fromMember": urn, "datePosted": date_posted, "sortBy": sort_by}
    if keyword:
        params["keyword"] = keyword
    try:
        data = _get("search/posts", params)
        inner = data.get("data", {})
        posts = inner if isinstance(inner, list) else inner.get("elements", inner.get("results", []))
        return posts, 1
    except Exception as exc:
        logger.warning("search/posts failed for urn %s: %s", urn, exc)
        return [], 1


def _company_posts(company_id: str) -> tuple[list[dict], int]:
    try:
        data = _get("companies/company/posts", {"id": company_id, "start": 0})
        inner = data.get("data", {})
        posts = inner if isinstance(inner, list) else inner.get("elements", inner.get("posts", []))
        return posts, 1
    except Exception as exc:
        logger.warning("company posts failed for id %s: %s", company_id, exc)
        return [], 1


def _post_age_days(post: dict) -> Optional[float]:
    posted_at = post.get("postedAt")
    if isinstance(posted_at, dict):
        ts = posted_at.get("timestamp")
        if ts is not None:
            return (time.time() * 1000 - ts) / (1000 * 86400)
    return None


def _post_text(post: dict) -> str:
    return post.get("text", "") or ""


def _post_id(post: dict) -> str:
    return post.get("urn") or post.get("postID") or post.get("postURL", "") or ""


def _classify_rule_based(posts: list[dict]) -> tuple[str, str, list[str], list[dict]]:
    """Returns (tier, confidence, signals, evidence_posts)."""
    direct_evidence: list[dict] = []
    indirect_evidence: list[dict] = []
    direct_signals: list[str] = []
    indirect_signals: list[str] = []

    for post in posts:
        text = _post_text(post)
        if not text:
            continue
        age = _post_age_days(post)
        age_label = f"{int(age)}d ago" if age is not None else "age unknown"
        ev = {
            "text": text[:300],
            "postedAt": post.get("postedAt"),
            "url": post.get("postURL") or post.get("url", ""),
            "totalReactions": (post.get("engagements") or {}).get("totalReactions"),
        }
        snippet = f'"{text[:80].replace(chr(10), " ")}"'

        if _DIRECT_PATTERNS.search(text):
            direct_evidence.append(ev)
            direct_signals.append(f"Direct hiring post ({age_label}): {snippet}")
        elif _INDIRECT_PATTERNS.search(text):
            indirect_evidence.append(ev)
            indirect_signals.append(f"Growth/funding post ({age_label}): {snippet}")

    if direct_evidence:
        ages = [a for p in direct_evidence if (a := _post_age_days(p)) is not None]
        recent = min(ages) if ages else None
        if recent is not None and recent <= 30:
            confidence = "high"
        elif recent is not None and recent <= 90:
            confidence = "medium"
        else:
            confidence = "low"
        return "direct", confidence, direct_signals, direct_evidence

    if indirect_evidence:
        ages = [a for p in indirect_evidence if (a := _post_age_days(p)) is not None]
        recent = min(ages) if ages else None
        confidence = "medium" if recent is not None and recent <= 60 else "low"
        return "indirect", confidence, indirect_signals, indirect_evidence

    return "none", "low", [], []


def _classify_with_haiku(posts: list[dict], company_name: str) -> tuple[str, str, list[str]]:
    try:
        import anthropic

        post_texts = "\n\n---\n\n".join(
            f"[Post {i+1}]\n{_post_text(p)[:500]}"
            for i, p in enumerate(posts[:10])
            if _post_text(p)
        )
        if not post_texts:
            return "none", "low", []

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": (
                    f"Given these recent LinkedIn posts from the founder of {company_name}, "
                    "does any post suggest the company is hiring engineers or growing the team?\n"
                    "Return JSON only: "
                    '{"hiring_likely": bool, "tier": "direct"|"indirect"|"none", '
                    '"confidence": "high"|"medium"|"low", "reason": str}\n\n'
                    f"Posts:\n{post_texts}"
                ),
            }],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"```[a-z]*\n?", "", raw).strip().rstrip("`").strip()
        result = json.loads(raw)
        if result.get("hiring_likely"):
            return (
                result.get("tier", "indirect"),
                result.get("confidence", "medium"),
                [f"Haiku: {result.get('reason', '')}"],
            )
        return "none", "low", []
    except Exception as exc:
        logger.warning("Haiku classification failed: %s", exc)
        return "none", "low", []


def resolve_founder_linkedin(
    name: str,
    company_name: str,
    existing_url: Optional[str] = None,
) -> Optional[str]:
    """Return a LinkedIn URL for the founder.

    Returns existing_url (normalized) if it already contains linkedin.com/in/.
    Otherwise queries search/people with company fuzzy-match.
    Returns None if no confident match found.
    """
    if existing_url and "linkedin.com/in/" in existing_url:
        username = _username_from_url(existing_url)
        return f"https://www.linkedin.com/in/{username}" if username else existing_url

    try:
        data = _get("search/people", {"keyword": name, "currentCompany": company_name, "count": 5})
        inner = data.get("data", {})
        items = (
            inner if isinstance(inner, list)
            else inner.get("elements", inner.get("items", inner.get("results", [])))
        )
        for item in items:
            username = (
                item.get("username")
                or item.get("publicIdentifier")
                or _username_from_url(item.get("profileUrl") or item.get("url", ""))
            )
            if not username:
                continue
            item_company = (item.get("companyName") or item.get("currentCompany") or "").lower()
            if not item_company or company_name.lower()[:8] in item_company:
                return f"https://www.linkedin.com/in/{username}"
        return None
    except Exception as exc:
        logger.warning("resolve_founder_linkedin failed for %s @ %s: %s", name, company_name, exc)
        return None


def resolve_company_linkedin(
    company_name: str,
    existing_id: Optional[str] = None,
) -> Optional[str]:
    """Return the company LinkedIn numeric ID.

    Returns existing_id immediately if provided. Otherwise queries companies/name-lookup.
    Returns None if no match found.
    """
    if existing_id:
        return existing_id
    try:
        data = _get("companies/name-lookup", {"name": company_name})
        company_id = data.get("data", {}).get("id") or data.get("id")
        return str(company_id) if company_id else None
    except Exception as exc:
        logger.warning("resolve_company_linkedin failed for %s: %s", company_name, exc)
        return None


def get_hiring_signals(
    founder_linkedin_url: Optional[str] = None,
    company_linkedin_id: Optional[str] = None,
    lookback_days: int = 90,
    company_name: str = "",
) -> HiringSignalResult:
    """Detect hiring signals from LinkedIn posts.

    Always scans posts — isHiring flag is recorded as metadata but never causes early return
    since it may be stale. Post recency (from real timestamps) determines signal freshness.

    Classification: rule-based regex first; Haiku fallback when regex finds nothing.
    """
    result = HiringSignalResult(
        tier="none",
        confidence="low",
        founder_url_resolved=founder_linkedin_url,
        company_id_resolved=company_linkedin_id,
    )

    if not founder_linkedin_url and not company_linkedin_id:
        result.error = "No founder_linkedin_url or company_linkedin_id provided"
        return result

    credits = 0
    all_posts: list[dict] = []
    seen_ids: set[str] = set()

    def _collect(posts: list[dict]) -> None:
        for p in posts:
            pid = _post_id(p)
            if pid not in seen_ids:
                seen_ids.add(pid)
                all_posts.append(p)

    if founder_linkedin_url:
        username = _username_from_url(founder_linkedin_url)
        if not username:
            result.error = f"Could not parse username from URL: {founder_linkedin_url}"
            return result

        urn, c = _urn_from_username(username)
        credits += c

        if urn:
            profile, c = _profile_full(username)
            credits += c
            result.is_hiring_flag = profile.get("isHiring")

            broad, c = _search_posts(urn, date_posted="past-year", sort_by="date_posted")
            credits += c
            _collect(broad)

            targeted, c = _search_posts(urn, keyword="hiring", date_posted="past-year", sort_by="date_posted")
            credits += c
            _collect(targeted)

    if company_linkedin_id:
        company_ps, c = _company_posts(company_linkedin_id)
        credits += c
        _collect(company_ps)

    result.credits_used = credits

    if not all_posts:
        if result.is_hiring_flag:
            result.tier = "direct"
            result.confidence = "low"
            result.signals = ["isHiring flag set on profile (no recent posts found to confirm)"]
        return result

    tier, confidence, signals, evidence = _classify_rule_based(all_posts)
    if tier == "none":
        tier, confidence, signals = _classify_with_haiku(all_posts, company_name or "this company")
        evidence = []

    if result.is_hiring_flag:
        if tier == "none":
            tier = "direct"
            confidence = "low"
            signals = ["isHiring flag set on profile (posts don't confirm active hiring)"]
        elif confidence == "low":
            confidence = "medium"
            signals.append("isHiring flag also set on profile")

    result.tier = tier
    result.confidence = confidence
    result.signals = signals
    result.evidence_posts = evidence
    return result
