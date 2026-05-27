"""pipeline_v2/mcp_server/server.py

FastMCP server exposing pipeline v2 tools.

Run standalone (stdio transport for Claude Desktop / any MCP host):
    python -m pipeline_v2.mcp_server.server

pipeline_v2 nodes should NOT import this module — they use
pipeline_v2.lib.tool_router, which calls the same tool functions
in-process.

Recommended agent pattern:
    recon_site(url) → inspect signals → pick Firecrawl tool
"""

from mcp.server.fastmcp import FastMCP

from tools.export import export as _export
from pipeline_v2.mcp_server.tools.scrape_yc_algolia_v2 import scrape_yc_algolia
from pipeline_v2.mcp_server.tools.recon_v2 import recon
from pipeline_v2.mcp_server.tools.linkdapi_v2 import (
    resolve_founder_linkedin as _resolve_founder_linkedin,
    resolve_company_linkedin as _resolve_company_linkedin,
    get_hiring_signals as _get_hiring_signals,
)
from pipeline_v2.mcp_server.tools.firecrawl_v2 import (
    search_web as _search_web,
    scrape_web_page as _scrape_web_page,
    search_web_and_scrape as _search_web_and_scrape,
    map_site as _map_site,
    crawl_site as _crawl_site,
    interact_with_page as _interact_with_page,
    continue_interaction as _continue_interaction,
    stop_interaction as _stop_interaction,
    open_browser_session as _open_browser_session,
    run_in_browser as _run_in_browser,
    close_browser_session as _close_browser_session,
    crawl_site_streaming as _crawl_site_streaming,
)

mcp = FastMCP("pipeline-v2-tools")


@mcp.tool()
def find_yc_companies(batches: list[str] | None = None) -> list[dict]:
    """Fetch AI-focused YC companies from the Algolia index.

    Args:
        batches: YC batch IDs to query, e.g. ["W25", "S25"].
                 Defaults to the last 3 years of batches.
    """
    return scrape_yc_algolia(batches=batches)


@mcp.tool()
def recon_site(url: str) -> str:
    """Pre-flight site analysis — run this before any Firecrawl tool.

    Returns JSON string with: blocked, backend, js_heavy, js_frameworks,
    pagination, sitemap, robots, visible_word_count, links, clean_text.

    Use the output to decide which Firecrawl tool to call next:
    - blocked=true → don't scrape, try search_web instead
    - js_heavy=true → scrape_web_page (Firecrawl renders JS)
    - sitemap found or deep link patterns → map_site first
    - need full site section → crawl_site
    """
    return recon(url)


@mcp.tool()
def search_web(query: str, limit: int = 5) -> list[dict]:
    """Search the web via Firecrawl. Returns {title, url, description} per result."""
    return _search_web(query, limit=limit)


@mcp.tool()
def scrape_web_page(url: str, formats: list[str] | None = None) -> dict:
    """Scrape a single URL. Firecrawl handles JS-rendered pages.

    Args:
        url: Full URL to scrape.
        formats: Output formats to request, e.g. ["markdown"], ["markdown", "html"].
                 Defaults to ["markdown"].

    Returns {url, markdown, html, metadata, error}.
    """
    return _scrape_web_page(url, formats=formats)


@mcp.tool()
def search_web_and_scrape(query: str, limit: int = 3) -> list[dict]:
    """Search the web and return full markdown content for each result page.

    Returns list of {url, title, markdown} dicts.
    """
    return _search_web_and_scrape(query, limit=limit)


@mcp.tool()
def map_site(url: str, limit: int = 20, search: str | None = None) -> list[str]:
    """Discover all URLs on a website.

    Args:
        url: Root URL.
        limit: Max URLs to return.
        search: Optional keyword to filter URLs.
    """
    return _map_site(url, limit=limit, search=search)


@mcp.tool()
def crawl_site(url: str, limit: int = 10) -> list[dict]:
    """Crawl an entire site (blocking). Returns list of {url, markdown} page dicts."""
    return _crawl_site(url, limit=limit)


@mcp.tool()
def interact_with_page(url: str, actions: list[dict], formats: list[str] | None = None) -> dict:
    """Interact with a webpage via browser automation, then scrape the result.

    Use when scrape_web_page returns incomplete content because the page
    requires login, button clicks, infinite scroll, or modal dismissal.

    actions is a list of steps to perform before scraping:
      [{"type": "scroll", "direction": "down", "amount": 500},
       {"type": "wait", "milliseconds": 1000},
       {"type": "click", "selector": "button.load-more"},
       {"type": "fill", "selector": "input[name='email']", "value": "..."}]

    formats: Output formats, e.g. ["markdown"] (default) or ["markdown", "html"].

    Returns {url, markdown, html, metadata, error}.
    """
    return _interact_with_page(url, actions=actions, formats=formats)


@mcp.tool()
def continue_interaction(scrape_job_id: str, code: str, language: str = "python") -> dict:
    """Continue interacting with the browser context from a prior scrape job.

    Use for act → observe → act flows after interact_with_page or scrape_web_page.
    The scrape_job_id is the "scrape_id" field in the return dict from
    scrape_web_page() or interact_with_page().
    The first call auto-initializes the session; subsequent calls reuse it.
    Always call stop_interaction(scrape_job_id) when done.

    Returns {stdout, result, error}.
    """
    return _continue_interaction(scrape_job_id, code=code, language=language)


@mcp.tool()
def stop_interaction(scrape_job_id: str) -> dict:
    """Stop a scrape-bound interactive session.

    Call this when done with continue_interaction() to free the live browser context.
    Returns {stopped, error}.
    """
    return _stop_interaction(scrape_job_id)


@mcp.tool()
def open_browser_session(profile_name: str | None = None) -> dict:
    """Open a persistent Playwright browser session for multi-step interactions.

    Args:
        profile_name: Optional named profile to save/restore cookies and
                      localStorage across sessions (stored on Firecrawl's infra).

    Returns {session_id, cdp_url, live_view_url, error}. Use session_id with
    run_in_browser() for each step. Always close with close_browser_session().

    Use this when continue_interaction is not enough — login flows requiring
    cross-page cookie persistence, CDP-level Playwright control, or sessions
    that span unrelated pages.
    """
    return _open_browser_session(profile_name=profile_name)


@mcp.tool()
def run_in_browser(session_id: str, code: str, language: str = "python") -> dict:
    """Execute Playwright code in an open browser session.

    Args:
        session_id: From open_browser_session()["session_id"].
        code: Python (default) or Node.js Playwright code. `page` is available.
              Examples:
              'await page.goto("https://example.com/login")'
              'await page.fill("input[name=email]", "user@example.com")'
              'content = await page.content(); print(content)'
        language: "python" or "node"

    Returns {stdout, result, error}.
    """
    return _run_in_browser(session_id, code=code, language=language)


@mcp.tool()
def close_browser_session(session_id: str) -> dict:
    """Close an open browser session. Always call this when done.

    Returns {closed, error}.
    """
    return _close_browser_session(session_id)


@mcp.tool()
def crawl_site_streaming(url: str, limit: int = 5) -> list[dict]:
    """Crawl a site with real-time WebSocket updates.

    Returns list of snapshot dicts with status, completed, total, and pages.
    """
    return _crawl_site_streaming(url, limit=limit)


@mcp.tool()
def find_founder_linkedin(
    name: str,
    company_name: str,
    existing_url: str | None = None,
) -> str | None:
    """Resolve a founder's LinkedIn URL.

    Returns existing_url as-is if it already contains linkedin.com/in/.
    Otherwise searches LinkedIn by name + company and returns the best match URL.
    Returns None if no confident match found.
    """
    return _resolve_founder_linkedin(name, company_name, existing_url=existing_url)


@mcp.tool()
def find_company_linkedin(
    company_name: str,
    existing_id: str | None = None,
) -> str | None:
    """Resolve a company's LinkedIn numeric ID.

    Returns existing_id immediately if provided. Otherwise queries LinkedIn by name.
    Returns None if no match found.
    """
    return _resolve_company_linkedin(company_name, existing_id=existing_id)


@mcp.tool()
def check_hiring_signals(
    founder_linkedin_url: str | None = None,
    company_linkedin_id: str | None = None,
    company_name: str = "",
) -> dict:
    """Detect hiring signals from a founder's and company's LinkedIn posts.

    Scans posts from the last year. Classification:
    - direct: explicit hiring language ("we're hiring", "join our team")
    - indirect: growth/funding signals ("we raised", "seed round")
    - none: no signals found

    Confidence reflects post recency — a hiring post from 2 weeks ago is high confidence;
    one from 10 months ago is low (likely already filled).

    Returns a dict with: tier, confidence, signals, evidence_posts, is_hiring_flag,
    founder_url_resolved, company_id_resolved, credits_used, error.
    """
    result = _get_hiring_signals(
        founder_linkedin_url=founder_linkedin_url,
        company_linkedin_id=company_linkedin_id,
        company_name=company_name,
    )
    return result.to_dict()


@mcp.tool()
def export_to_excel(output_path: str | None = None) -> str:
    """Export the full pipeline database to a multi-sheet Excel file.

    Writes four sheets: Companies, Scores, Outreach Drafts, Research.
    Saves to reports/outreach_export_<timestamp>.xlsx by default.

    Args:
        output_path: Optional custom file path for the export.

    Returns the path of the written file.
    """
    return _export(output_path=output_path)


if __name__ == "__main__":
    mcp.run()
