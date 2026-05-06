"""
browser.py — AccessScan shared Playwright browser manager.

Provides a single, reusable browser context for all auditors.
Eliminates the per-route browser spawning from the old codebase.

Usage:
    # One-off page (auto-cleanup):
    with browser_page(url) as page:
        result = audit_page(url, page=page)

    # Reuse across multiple pages (sitemap scanner):
    with browser_context() as context:
        for url in urls:
            page = context.new_page()
            result = audit_page(url, page=page)
            page.close()

    # Fetch raw bytes (PDF/DOCX download):
    pdf_bytes = fetch_bytes(pdf_url)
"""
from __future__ import annotations

import contextlib
import os
from typing import Generator, Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
    Playwright,
)

# ── Configuration ─────────────────────────────────────────────────────────────

# User agent mimics a real Chrome browser to avoid bot-detection blocks
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_VIEWPORT = {"width": 1280, "height": 800}
DEFAULT_TIMEOUT   = 60_000   # 60 seconds
NETWORK_IDLE_WAIT = 3_000    # 3 seconds after networkidle for dynamic content

# Screenshot output directory (for scan evidence)
SCAN_EVIDENCE_DIR = os.path.join("static", "scans")


# ── Context managers ──────────────────────────────────────────────────────────

@contextlib.contextmanager
def browser_context(
    headless: bool = True,
    disable_web_security: bool = False,
) -> Generator[BrowserContext, None, None]:
    """
    Context manager that yields a reusable BrowserContext.
    Use this when you need to open multiple pages (e.g. sitemap scanner).

    Args:
        headless:             Run without a visible browser window.
        disable_web_security: Set True only for embed scanning that needs
                              cross-origin frame inspection. Never enable
                              for production server deployments.

    Example:
        with browser_context() as ctx:
            for url in urls:
                page = ctx.new_page()
                do_something(page, url)
                page.close()
    """
    args = ["--disable-dev-shm-usage"]  # Needed for Docker/Linux environments
    if disable_web_security:
        # Only used for embed checker — inspects cross-origin iframe content
        args.append("--disable-web-security")

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(
            headless=headless,
            args=args,
        )
        context: BrowserContext = browser.new_context(
            user_agent=USER_AGENT,
            viewport=DEFAULT_VIEWPORT,
            ignore_https_errors=True,  # Allow self-signed certs on intranets
        )
        context.set_default_timeout(DEFAULT_TIMEOUT)

        try:
            yield context
        finally:
            context.close()
            browser.close()


@contextlib.contextmanager
def browser_page(
    url: Optional[str] = None,
    headless: bool = True,
    disable_web_security: bool = False,
    wait_until: str = "networkidle",
) -> Generator[Page, None, None]:
    """
    Context manager that yields a single ready-to-use Page.
    Use this for one-off audits (embed checker, single PDF page scan).

    Args:
        url:         If provided, navigates to the URL before yielding.
        headless:    Run without a visible browser window.
        wait_until:  Playwright navigation wait strategy.
                     "networkidle" — waits for no network activity (thorough)
                     "domcontentloaded" — faster, less complete

    Example:
        with browser_page("https://example.com") as page:
            html = page.content()
    """
    with browser_context(
        headless=headless,
        disable_web_security=disable_web_security,
    ) as context:
        page: Page = context.new_page()

        if url:
            page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until=wait_until)
            # Extra wait for JavaScript-heavy pages
            page.wait_for_timeout(NETWORK_IDLE_WAIT)

        try:
            yield page
        finally:
            page.close()


def get_page_context(url: str) -> tuple[Page, callable]:
    """
    Non-context-manager version for use inside async/generator routes
    where 'with' blocks are awkward (e.g. SSE streaming).

    Returns (page, cleanup_fn). Caller MUST call cleanup_fn() when done.

    Example:
        page, cleanup = get_page_context(url)
        try:
            result = audit_page(url, page=page)
        finally:
            cleanup()
    """
    playwright_instance: Playwright = sync_playwright().start()
    browser: Browser = playwright_instance.chromium.launch(
        headless=True,
        args=["--disable-dev-shm-usage"],
    )
    context: BrowserContext = browser.new_context(
        user_agent=USER_AGENT,
        viewport=DEFAULT_VIEWPORT,
        ignore_https_errors=True,
    )
    context.set_default_timeout(DEFAULT_TIMEOUT)
    page: Page = context.new_page()

    def cleanup():
        try:
            page.close()
        except Exception:
            pass
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        try:
            playwright_instance.stop()
        except Exception:
            pass

    return page, cleanup


# ── File fetching ─────────────────────────────────────────────────────────────

def fetch_bytes(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """
    Download a file (PDF, DOCX) and return raw bytes.
    Uses Playwright's request context to share cookies/auth with the browser.

    Args:
        url:     Absolute URL to fetch.
        timeout: Request timeout in milliseconds.

    Returns:
        Raw file bytes.

    Raises:
        RuntimeError: If the request fails or returns a non-200 status.
    """
    with browser_context() as context:
        response = context.request.get(url, timeout=timeout)
        if response.status != 200:
            raise RuntimeError(
                f"Failed to fetch {url}: HTTP {response.status}"
            )
        return response.body()


def fetch_bytes_from_page(page: Page, url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """
    Download a file using an existing page's request context.
    Use this when you already have a browser page open (avoids spinning up
    a second browser just to download a file).

    Args:
        page:    Existing Playwright Page object.
        url:     Absolute URL to fetch.
        timeout: Request timeout in milliseconds.

    Returns:
        Raw file bytes.

    Raises:
        RuntimeError: If the request fails.
    """
    response = page.context.request.get(url, timeout=timeout)
    if response.status != 200:
        raise RuntimeError(
            f"Failed to fetch {url}: HTTP {response.status}"
        )
    return response.body()


# ── Screenshot (scan evidence) ────────────────────────────────────────────────

def take_evidence_screenshot(page: Page, label: str = "scan") -> str:
    """
    Take a full-page screenshot and save it to the scan evidence directory.

    Returns the relative URL path to the screenshot for frontend display,
    e.g. "/static/scans/scan_1234567890.png"
    """
    import time

    os.makedirs(SCAN_EVIDENCE_DIR, exist_ok=True)
    filename = f"{label}_{int(time.time())}.png"
    path = os.path.join(SCAN_EVIDENCE_DIR, filename)

    try:
        page.screenshot(path=path, full_page=True)
        return f"/static/scans/{filename}"
    except Exception:
        return ""


def highlight_elements(page: Page, selector: str) -> None:
    """
    Inject visual highlight markers onto matching elements.
    Used to generate scan evidence screenshots.

    Args:
        page:     Playwright Page.
        selector: CSS selector for elements to highlight.
    """
    try:
        page.evaluate(f"""
            (selector) => {{
                const elements = document.querySelectorAll(selector);
                elements.forEach((el, i) => {{
                    el.style.outline = '4px solid #cc0000';
                    el.style.outlineOffset = '2px';

                    const badge = document.createElement('div');
                    badge.textContent = '#' + (i + 1);
                    badge.style.cssText = [
                        'position: absolute',
                        'background: #cc0000',
                        'color: white',
                        'padding: 2px 6px',
                        'font-size: 12px',
                        'font-weight: bold',
                        'z-index: 2147483647',
                        'pointer-events: none',
                        'border-radius: 3px',
                        'font-family: monospace',
                    ].join(';');

                    const rect = el.getBoundingClientRect();
                    badge.style.top  = (rect.top  + window.scrollY) + 'px';
                    badge.style.left = (rect.left + window.scrollX) + 'px';
                    document.body.appendChild(badge);
                }});
            }}
        """, selector)
    except Exception:
        pass


# ── Embed-specific browser (cross-origin) ────────────────────────────────────

@contextlib.contextmanager
def embed_browser_page(url: str) -> Generator[Page, None, None]:
    """
    Specialized browser page for embed/iframe scanning.
    Disables web security to allow cross-origin frame inspection.

    IMPORTANT: Only use locally. Never expose this to public internet traffic.
    """
    with browser_page(
        url=url,
        disable_web_security=True,
        wait_until="networkidle",
    ) as page:
        # Extra wait for dynamically injected iframes (ad networks, etc.)
        page.wait_for_timeout(NETWORK_IDLE_WAIT)
        yield page