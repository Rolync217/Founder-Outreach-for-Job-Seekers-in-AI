"""pipeline_v2/lib/tool_router.py

Single import point for all pipeline v2 execution-layer tools.
Pipeline nodes import from here — not from mcp_server/tools/ directly.

    from pipeline_v2.lib.tool_router import recon_site, search_web, scrape_web_page

Use recon_site(url) when you need structure, blockage checks, or tool routing hints.
"""

from pipeline_v2.mcp_server.tools.scrape_yc_algolia_v2 import scrape_yc_algolia as find_yc_companies
from pipeline_v2.mcp_server.tools.recon_v2 import recon as recon_site
from pipeline_v2.mcp_server.tools.firecrawl_v2 import (
    search_web,
    scrape_web_page,
    search_web_and_scrape,
    map_site,
    crawl_site,
    interact_with_page,
    continue_interaction,
    stop_interaction,
    open_browser_session,
    run_in_browser,
    close_browser_session,
    crawl_site_streaming,
)
from pipeline_v2.mcp_server.tools.linkdapi_v2 import (
    resolve_founder_linkedin,
    resolve_company_linkedin,
    get_hiring_signals,
    HiringSignalResult,
)

__all__ = [
    "find_yc_companies",
    "recon_site",
    "search_web",
    "scrape_web_page",
    "search_web_and_scrape",
    "map_site",
    "crawl_site",
    "interact_with_page",
    "continue_interaction",
    "stop_interaction",
    "open_browser_session",
    "run_in_browser",
    "close_browser_session",
    "crawl_site_streaming",
    "resolve_founder_linkedin",
    "resolve_company_linkedin",
    "get_hiring_signals",
    "HiringSignalResult",
]
