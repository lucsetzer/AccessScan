"""
page.py — AccessScan HTML page accessibility auditor.

Uses axe-core (industry standard) via Playwright for automated checks,
supplemented by custom checks for issues axe-core does not cover well.

Automated checks (via axe-core):
  - Images missing alt text (WCAG 1.1.1)
  - Form inputs missing labels (WCAG 1.3.1 / 3.3.2)
  - Color contrast failures (WCAG 1.4.3)
  - Landmark regions (WCAG 1.3.1)
  - Heading structure (WCAG 1.3.1 / 2.4.6)
  - Link purpose (WCAG 2.4.4)
  - Page language (WCAG 3.1.1)
  - Page title (WCAG 2.4.2)
  - Keyboard traps (WCAG 2.1.2)
  - Skip navigation links (WCAG 2.4.1)
  - ARIA usage validity (WCAG 4.1.2)
  - Button names (WCAG 4.1.2)
  - Table headers (WCAG 1.3.1)

Custom checks (supplemental):
  - PDF links found on page (triggers pdf auditor)
  - DOCX links found on page (triggers docx auditor)
  - iframes / embeds found (triggers embed auditor)
  - Viewport meta tag (mobile accessibility)
  - Focus visible check (WCAG 2.4.7)
"""
from __future__ import annotations

import json
from typing import Optional
from urllib.parse import urljoin

from core.schema import AuditResult, Finding, Tier, make_finding

# axe-core CDN — pinned version for reproducibility
AXE_CORE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"

# axe-core impact → our Tier mapping
AXE_IMPACT_MAP = {
    "critical":  Tier.CRITICAL,
    "serious":   Tier.CRITICAL,
    "moderate":  Tier.WARNING,
    "minor":     Tier.WARNING,
}

# axe-core rule ID → WCAG criterion mapping
# Only the most important ones — axe provides its own tags too
AXE_RULE_CRITERION: dict[str, str] = {
    "image-alt":              "WCAG 1.1.1",
    "input-image-alt":        "WCAG 1.1.1",
    "area-alt":               "WCAG 1.1.1",
    "label":                  "WCAG 3.3.2",
    "label-content-name-mismatch": "WCAG 2.5.3",
    "color-contrast":         "WCAG 1.4.3",
    "color-contrast-enhanced": "WCAG 1.4.6",
    "landmark-one-main":      "WCAG 1.3.1",
    "region":                 "WCAG 1.3.1",
    "heading-order":          "WCAG 1.3.1",
    "empty-heading":          "WCAG 2.4.6",
    "page-has-heading-one":   "WCAG 2.4.6",
    "link-name":              "WCAG 2.4.4",
    "link-in-text-block":     "WCAG 1.4.1",
    "html-has-lang":          "WCAG 3.1.1",
    "html-lang-valid":        "WCAG 3.1.1",
    "document-title":         "WCAG 2.4.2",
    "frame-title":            "WCAG 4.1.2",
    "frame-title-unique":     "WCAG 4.1.2",
    "button-name":            "WCAG 4.1.2",
    "aria-allowed-attr":      "WCAG 4.1.2",
    "aria-required-attr":     "WCAG 4.1.2",
    "aria-valid-attr":        "WCAG 4.1.2",
    "aria-valid-attr-value":  "WCAG 4.1.2",
    "aria-hidden-focus":      "WCAG 2.1.1",
    "bypass":                 "WCAG 2.4.1",
    "skip-link":              "WCAG 2.4.1",
    "tabindex":               "WCAG 2.4.3",
    "th-has-data-cells":      "WCAG 1.3.1",
    "td-headers-attr":        "WCAG 1.3.1",
    "table-duplicate-name":   "WCAG 1.3.1",
    "scrollable-region-focusable": "WCAG 2.1.1",
    "meta-viewport":          "WCAG 1.4.4",
    "target-size":            "WCAG 2.5.8",
}


def audit_page(url: str, page=None) -> AuditResult:
    """
    Run a full accessibility audit on a live HTML page.

    Args:
        url:  The page URL to audit.
        page: Optional existing Playwright page object (from browser.py).
              If None, a new browser context is opened.

    Returns:
        AuditResult with all findings.
    """
    findings: list[Finding] = []
    metadata: dict = {"url": url}
    owns_browser = page is None

    try:
        if owns_browser:
            from core.browser import get_page_context
            ctx_manager = get_page_context(url)
            page, browser_cleanup = ctx_manager
        else:
            browser_cleanup = None

        # Navigate to the page
        try:
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(1000)  # Allow dynamic content to settle
        except Exception as nav_err:
            return AuditResult(
                source_type="page",
                source_label=url,
                findings=[],
                error=f"Could not load page: {str(nav_err)}",
            )

        # ── Inject and run axe-core ───────────────────────────────────────────
        axe_findings, axe_meta = _run_axe(page, url)
        findings.extend(axe_findings)
        metadata.update(axe_meta)

        # ── Custom checks ─────────────────────────────────────────────────────
        findings.extend(_check_viewport_meta(page))
        findings.extend(_check_focus_visible(page))

        # Collect linked file URLs for the sitemap scanner to process
        pdf_urls = _find_linked_pdfs(page, url)
        docx_urls = _find_linked_docx(page, url)
        embed_snippets = _find_embed_snippets(page)

        metadata["pdf_urls"] = pdf_urls
        metadata["docx_urls"] = docx_urls
        metadata["embed_snippets"] = embed_snippets
        metadata["pdf_count"] = len(pdf_urls)
        metadata["docx_count"] = len(docx_urls)
        metadata["embed_count"] = len(embed_snippets)

        return AuditResult(
            source_type="page",
            source_label=url,
            findings=findings,
            metadata=metadata,
        )

    except Exception as e:
        return AuditResult(
            source_type="page",
            source_label=url,
            findings=[],
            error=f"Page audit failed: {str(e)}",
        )
    finally:
        if owns_browser and browser_cleanup:
            try:
                browser_cleanup()
            except Exception:
                pass


# ── axe-core runner ───────────────────────────────────────────────────────────

def _run_axe(page, url: str) -> tuple[list[Finding], dict]:
    """
    Inject axe-core into the page, run it, and convert violations to Findings.
    """
    findings: list[Finding] = []
    meta: dict = {}

    try:
        # Inject axe-core from CDN if not already present
        axe_present = page.evaluate("() => typeof axe !== 'undefined'")
        if not axe_present:
            page.add_script_tag(url=AXE_CORE_CDN)
            page.wait_for_timeout(500)  # Let the script load

        # Run axe with WCAG 2.1 AA rules (covers all Level A and AA)
        axe_result_json = page.evaluate("""
            async () => {
                const results = await axe.run(document, {
                    runOnly: {
                        type: 'tag',
                        values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']
                    },
                    resultTypes: ['violations', 'incomplete'],
                    reporter: 'v2'
                });
                return JSON.stringify({
                    violations: results.violations,
                    incomplete: results.incomplete,
                    passes_count: results.passes.length,
                    inapplicable_count: results.inapplicable.length,
                    url: results.url,
                    timestamp: results.timestamp
                });
            }
        """)

        axe_data = json.loads(axe_result_json)
        meta["axe_passes"] = axe_data.get("passes_count", 0)
        meta["axe_inapplicable"] = axe_data.get("inapplicable_count", 0)

        # Convert violations to Findings
        for violation in axe_data.get("violations", []):
            tier = AXE_IMPACT_MAP.get(violation.get("impact", "minor"), Tier.WARNING)
            criterion = AXE_RULE_CRITERION.get(violation.get("id", ""), "")

            # Build a location string from affected nodes (up to 3)
            nodes = violation.get("nodes", [])
            locations = []
            for node in nodes[:3]:
                target = node.get("target", [])
                if target:
                    locations.append(str(target[0]))
            location = ", ".join(locations) if locations else None

            # Use axe's own help text for description and fix
            description = violation.get("description", violation.get("help", ""))
            fix_hint = _build_fix_hint(violation)

            findings.append(make_finding(
                tier=tier,
                description=description,
                fix_hint=fix_hint,
                criterion=criterion,
                technique=violation.get("id", ""),  # axe rule ID as technique ref
                location=location,
            ))

        # Convert incomplete (needs review) to manual findings
        for incomplete in axe_data.get("incomplete", []):
            criterion = AXE_RULE_CRITERION.get(incomplete.get("id", ""), "")
            nodes = incomplete.get("nodes", [])
            locations = []
            for node in nodes[:3]:
                target = node.get("target", [])
                if target:
                    locations.append(str(target[0]))
            location = ", ".join(locations) if locations else None

            findings.append(make_finding(
                tier=Tier.MANUAL,
                description=f"Needs manual review: {incomplete.get('description', incomplete.get('help', ''))}",
                fix_hint=_build_fix_hint(incomplete),
                criterion=criterion,
                technique=incomplete.get("id", ""),
                location=location,
            ))

    except Exception as axe_err:
        # axe-core failed to load or run — fall back to manual notice
        findings.append(make_finding(
            Tier.MANUAL,
            f"Automated axe-core scan could not complete: {str(axe_err)[:120]}. "
            "Manual testing is required.",
            "Use the axe DevTools browser extension or NVDA/VoiceOver to manually "
            "test this page.",
            "",
        ))

    return findings, meta


def _build_fix_hint(axe_item: dict) -> str:
    """Build a plain-English fix hint from axe-core violation data."""
    help_url = axe_item.get("helpUrl", "")
    nodes = axe_item.get("nodes", [])

    hints = []

    # Collect fix suggestions from node failure summaries
    for node in nodes[:2]:
        for check_type in ("any", "all", "none"):
            for check in node.get(check_type, []):
                msg = check.get("message", "")
                if msg and msg not in hints:
                    hints.append(msg)

    base_hint = " ".join(hints[:2]) if hints else axe_item.get("help", "")

    if help_url:
        base_hint = f"{base_hint} See: {help_url}".strip()

    return base_hint or "Review this element for accessibility compliance."


# ── Custom checks ─────────────────────────────────────────────────────────────

def _check_viewport_meta(page) -> list[Finding]:
    """
    Check for viewport meta tag that disables user scaling.
    user-scalable=no or maximum-scale=1.0 prevents zoom, which is
    a WCAG 1.4.4 failure.
    """
    findings = []
    try:
        viewport_content = page.evaluate("""
            () => {
                const meta = document.querySelector('meta[name="viewport"]');
                return meta ? meta.getAttribute('content') : null;
            }
        """)

        if viewport_content is None:
            findings.append(make_finding(
                Tier.WARNING,
                "No viewport meta tag found. Mobile users may experience "
                "display issues.",
                'Add <meta name="viewport" content="width=device-width, '
                'initial-scale=1"> to the <head>.',
                "WCAG 1.4.4",
            ))
        else:
            content_lower = viewport_content.lower()
            disables_zoom = (
                "user-scalable=no" in content_lower
                or "user-scalable=0" in content_lower
                or "maximum-scale=1" in content_lower
                or "maximum-scale=1.0" in content_lower
            )
            if disables_zoom:
                findings.append(make_finding(
                    Tier.CRITICAL,
                    f'Viewport meta disables user zoom: content="{viewport_content}". '
                    "Users who need to enlarge text cannot do so.",
                    'Remove user-scalable=no and maximum-scale=1 from the viewport meta. '
                    'Use: <meta name="viewport" content="width=device-width, initial-scale=1">',
                    "WCAG 1.4.4",
                ))
    except Exception:
        pass

    return findings


def _check_focus_visible(page) -> list[Finding]:
    """
    Check if the page suppresses focus outlines globally via CSS.
    outline:0 or outline:none on :focus without a replacement is a
    WCAG 2.4.7 failure.
    """
    findings = []
    try:
        suppresses_focus = page.evaluate("""
            () => {
                // Inject a test element and check computed style on :focus
                const style = document.createElement('style');
                style.textContent = '.__a11y_test_focus:focus { color: rgb(1,2,3); }';
                document.head.appendChild(style);

                const el = document.createElement('button');
                el.className = '__a11y_test_focus';
                el.style.position = 'absolute';
                el.style.top = '-9999px';
                document.body.appendChild(el);
                el.focus();

                const computed = window.getComputedStyle(el);
                const outlineWidth = computed.outlineWidth;
                const outlineStyle = computed.outlineStyle;

                // Check if any global rule suppresses outline
                const sheets = Array.from(document.styleSheets);
                let suppressedGlobally = false;
                for (const sheet of sheets) {
                    try {
                        const rules = Array.from(sheet.cssRules || []);
                        for (const rule of rules) {
                            if (rule.selectorText &&
                                rule.selectorText.includes(':focus') &&
                                rule.style &&
                                (rule.style.outline === 'none' ||
                                 rule.style.outline === '0' ||
                                 rule.style.outlineStyle === 'none')) {
                                // Check it's a broad selector (not a component override)
                                if (['*:focus', ':focus', '*'].some(s =>
                                    rule.selectorText.includes(s))) {
                                    suppressedGlobally = true;
                                }
                            }
                        }
                    } catch (e) { /* cross-origin sheet */ }
                }

                // Cleanup
                document.head.removeChild(style);
                document.body.removeChild(el);

                return suppressedGlobally;
            }
        """)

        if suppresses_focus:
            findings.append(make_finding(
                Tier.CRITICAL,
                "The page appears to globally suppress focus outlines (outline:none on :focus). "
                "Keyboard users cannot see which element is focused.",
                "Remove outline:none/:focus{outline:0} from global CSS. "
                "Replace with a custom visible focus style: "
                ":focus-visible { outline: 3px solid #005fcc; outline-offset: 2px; }",
                "WCAG 2.4.7",
            ))

    except Exception:
        pass

    return findings


# ── File/embed discovery ──────────────────────────────────────────────────────

def _find_linked_pdfs(page, base_url: str) -> list[str]:
    """Return list of absolute PDF URLs found as links on the page."""
    try:
        hrefs = page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                       .map(a => a.href)
                       .filter(h => h.toLowerCase().endsWith('.pdf'))
        """)
        return [urljoin(base_url, h) for h in hrefs if h]
    except Exception:
        return []


def _find_linked_docx(page, base_url: str) -> list[str]:
    """Return list of absolute DOCX URLs found as links on the page."""
    try:
        hrefs = page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                       .map(a => a.href)
                       .filter(h => h.toLowerCase().endsWith('.docx'))
        """)
        return [urljoin(base_url, h) for h in hrefs if h]
    except Exception:
        return []


def _find_embed_snippets(page) -> list[str]:
    """Return outerHTML of all iframe/video/audio/object/embed elements."""
    try:
        snippets = page.evaluate("""
            () => Array.from(
                    document.querySelectorAll('iframe, video, audio, object, embed')
                  ).map(el => el.outerHTML)
        """)
        return snippets or []
    except Exception:
        return []