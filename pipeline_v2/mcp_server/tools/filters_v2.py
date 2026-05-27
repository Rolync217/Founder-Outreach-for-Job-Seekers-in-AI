"""pipeline_v2/mcp_server/tools/filters_v2.py

Keyword filters for AI signal detection and sector exclusion.
Isolated copy of tools/filters.py for the MCP server boundary.
"""

AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "llm",
    "language model", "generative", "nlp", "computer vision",
    "ml", "neural", "foundation model", "agent", "pytorch",
    "tensorflow", "transformer", "embedding", "inference",
]

EXCLUDE_KEYWORDS = ["crypto", "web3", "blockchain", "nft", "defi", "dao"]


def has_ai_signal(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in AI_KEYWORDS)


def is_excluded(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in EXCLUDE_KEYWORDS)
