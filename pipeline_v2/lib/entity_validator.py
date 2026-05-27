import re

_REJECT_PATTERNS = [
    (r"\b(venture capital|vc firm|portfolio|fund)\b", "investor_or_fund"),
    (r"\b(newsletter|blog post|article|report|whitepaper|guide)\b", "article_or_content"),
    (r"\b(batch companies|batch startups|directory|landscape)\b", "category_page"),
    (r"\b(raises? \$|million raised|series [a-e] funding)\b", "funding_article"),
]


def validate_entity(entity: dict) -> tuple[bool, str]:
    name: str = (entity.get("name") or "").strip()
    url: str = entity.get("website") or entity.get("directory_url") or entity.get("url") or ""

    if not name or len(name) < 2:
        return False, "no_company_name"

    if not url:
        return False, "no_url"

    name_lower = name.lower()
    for pattern, label in _REJECT_PATTERNS:
        if re.search(pattern, name_lower):
            return False, label

    if len(name.split()) > 10:
        return False, "too_long_likely_article_title"

    return True, ""
