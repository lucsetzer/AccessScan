"""
main.py — AccessScan FastAPI application.

Routes:
    POST /api/audit/embed      — snippet or URL embed audit
    POST /api/audit/pdf        — file upload or URL PDF audit
    POST /api/audit/docx       — file upload or URL DOCX audit
    POST /api/audit/page       — full HTML page audit (axe-core + custom)
    POST /api/audit/sitemap    — sitemap scan (SSE streaming)
    POST /api/export           — export results as CSV, PDF, or JSON
    GET  /health               — health check

NOTE: FastAPI runs on asyncio. All Playwright calls use the sync API and must
be wrapped in asyncio.to_thread() to avoid "sync API inside asyncio loop" errors.
The pattern used throughout is:

    result = await asyncio.to_thread(_sync_fn, arg1, arg2)

where _sync_fn contains all Playwright code.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.schema import AuditResult, SitemapResult, Tier

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AccessScan",
    description="WCAG 2.2 accessibility auditor for web pages, PDFs, DOCX, and embeds.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(os.path.join("static", "scans"), exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Request models ────────────────────────────────────────────────────────────

class EmbedRequest(BaseModel):
    snippet: Optional[str] = None
    url: Optional[str] = None

class UrlRequest(BaseModel):
    url: str

class SitemapRequest(BaseModel):
    url: str
    scan_types: list[str] = ["page", "pdf", "docx", "embed"]
    max_urls: int = 50

class ExportRequest(BaseModel):
    format: str = "json"
    results: list[dict] = []


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "app": "AccessScan", "version": "1.0.0"}


# ── Embed audit ───────────────────────────────────────────────────────────────

@app.post("/api/audit/embed")
async def audit_embed_route(body: EmbedRequest):
    from core.auditors.embed import audit_embed

    snippet = (body.snippet or "").strip()
    url = (body.url or "").strip()

    if not snippet and not url:
        raise HTTPException(400, "Provide either a snippet or a URL.")

    # Snippet mode — no Playwright needed
    if snippet and not url:
        try:
            audit_results = audit_embed(snippet, source_label="HTML Snippet")
            return {
                "success": True,
                "source": "snippet",
                "count": len(audit_results),
                "results": [r.to_dict() for r in audit_results],
            }
        except Exception as e:
            raise HTTPException(500, f"Snippet audit failed: {str(e)}")

    # URL mode — Playwright required, run in thread
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    def _scan_url(target_url: str):
        from core.auditors.embed import audit_embed
        from core.browser import embed_browser_page, highlight_elements, take_evidence_screenshot
        results = []
        evidence_url = ""
        with embed_browser_page(target_url) as page:
            highlight_elements(page, "iframe, video, audio, object, embed")
            evidence_url = take_evidence_screenshot(page, label="embed")
            embeds = get_embeds_from_page(page, target_url)
            for item in embeds:
                item_snippet = item.get("snippet", "")
                if not item_snippet:
                    continue
                audit_results = audit_embed(
                    item_snippet,
                    metadata=item,
                    source_label=target_url,
                )
                for r in audit_results:
                    results.append(r.to_dict())
        return results, evidence_url

    try:
        results, evidence_url = await asyncio.to_thread(_scan_url, url)
        return {
            "success": True,
            "source": "url",
            "url": url,
            "count": len(results),
            "evidence_url": evidence_url,
            "results": results,
        }
    except Exception as e:
        raise HTTPException(500, f"URL scan failed: {str(e)}")


# ── PDF audit ─────────────────────────────────────────────────────────────────

@app.post("/api/audit/pdf")
async def audit_pdf_route(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
):
    from core.auditors.pdf import audit_pdf

    # File upload — no Playwright needed
    if file and file.filename:
        try:
            pdf_bytes = await file.read()
            result = audit_pdf(pdf_bytes, source_label=file.filename)
            return {"success": True, "source": "upload", "results": [result.to_dict()]}
        except Exception as e:
            raise HTTPException(500, f"PDF audit failed: {str(e)}")

    if not url:
        raise HTTPException(400, "Provide a file upload or a URL.")

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Direct PDF URL
    if url.lower().endswith(".pdf"):
        def _fetch_and_audit_pdf(target_url: str):
            from core.auditors.pdf import audit_pdf
            from core.browser import fetch_bytes
            pdf_bytes = fetch_bytes(target_url)
            result = audit_pdf(pdf_bytes, source_label=target_url.split("/")[-1])
            return result.to_dict()

        try:
            result = await asyncio.to_thread(_fetch_and_audit_pdf, url)
            return {"success": True, "source": "direct_url", "url": url, "results": [result]}
        except Exception as e:
            raise HTTPException(500, f"Failed to fetch PDF: {str(e)}")

    # HTML page — find and audit all linked PDFs
    def _scan_page_for_pdfs(target_url: str):
        from core.auditors.pdf import audit_pdf
        from core.browser import browser_page, fetch_bytes_from_page
        results = []
        with browser_page(target_url) as page:
            pdf_urls = _find_linked_pdfs(page, target_url)
            for pdf_url in pdf_urls:
                try:
                    pdf_bytes = fetch_bytes_from_page(page, pdf_url)
                    result = audit_pdf(pdf_bytes, source_label=pdf_url.split("/")[-1])
                    d = result.to_dict()
                    d["url"] = pdf_url
                    results.append(d)
                except Exception as e:
                    results.append({
                        "source_type": "pdf",
                        "source_label": pdf_url.split("/")[-1],
                        "url": pdf_url,
                        "error": str(e),
                        "findings": [],
                        "summary": _empty_summary(),
                    })
        return results

    try:
        results = await asyncio.to_thread(_scan_page_for_pdfs, url)
        return {
            "success": True,
            "source": "html_page",
            "url": url,
            "total_pdfs": len(results),
            "results": results,
            "combined_summary": _combine_summaries(results),
        }
    except Exception as e:
        raise HTTPException(500, f"Page PDF scan failed: {str(e)}")


# ── DOCX audit ────────────────────────────────────────────────────────────────

@app.post("/api/audit/docx")
async def audit_docx_route(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
):
    from core.auditors.docx import audit_docx

    # File upload — no Playwright needed
    if file and file.filename:
        if not file.filename.lower().endswith(".docx"):
            raise HTTPException(400, "Only .docx files are supported.")
        try:
            docx_bytes = await file.read()
            result = audit_docx(docx_bytes, source_label=file.filename)
            return {"success": True, "source": "upload", "results": [result.to_dict()]}
        except Exception as e:
            raise HTTPException(500, f"DOCX audit failed: {str(e)}")

    if not url:
        raise HTTPException(400, "Provide a file upload or a URL.")

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Direct DOCX URL
    if url.lower().endswith(".docx"):
        def _fetch_and_audit_docx(target_url: str):
            from core.auditors.docx import audit_docx
            from core.browser import fetch_bytes
            docx_bytes = fetch_bytes(target_url)
            result = audit_docx(docx_bytes, source_label=target_url.split("/")[-1])
            return result.to_dict()

        try:
            result = await asyncio.to_thread(_fetch_and_audit_docx, url)
            return {"success": True, "source": "direct_url", "url": url, "results": [result]}
        except Exception as e:
            raise HTTPException(500, f"Failed to fetch DOCX: {str(e)}")

    # HTML page — find and audit all linked DOCX files
    def _scan_page_for_docx(target_url: str):
        from core.auditors.docx import audit_docx
        from core.browser import browser_page, fetch_bytes_from_page
        results = []
        with browser_page(target_url) as page:
            docx_urls = _find_linked_docx(page, target_url)
            for docx_url in docx_urls:
                try:
                    docx_bytes = fetch_bytes_from_page(page, docx_url)
                    result = audit_docx(docx_bytes, source_label=docx_url.split("/")[-1])
                    d = result.to_dict()
                    d["url"] = docx_url
                    results.append(d)
                except Exception as e:
                    results.append({
                        "source_type": "docx",
                        "source_label": docx_url.split("/")[-1],
                        "url": docx_url,
                        "error": str(e),
                        "findings": [],
                        "summary": _empty_summary(),
                    })
        return results

    try:
        results = await asyncio.to_thread(_scan_page_for_docx, url)
        return {
            "success": True,
            "source": "html_page",
            "url": url,
            "total_docx": len(results),
            "results": results,
            "combined_summary": _combine_summaries(results),
        }
    except Exception as e:
        raise HTTPException(500, f"Page DOCX scan failed: {str(e)}")


# ── Page audit ────────────────────────────────────────────────────────────────

@app.post("/api/audit/page")
async def audit_page_route(body: UrlRequest):
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    def _audit(target_url: str):
        from core.auditors.page import audit_page
        from core.browser import browser_page
        with browser_page(target_url) as page:
            return audit_page(target_url, page=page).to_dict()

    try:
        result = await asyncio.to_thread(_audit, url)
        return {"success": True, "results": [result]}
    except Exception as e:
        raise HTTPException(500, f"Page audit failed: {str(e)}")


# ── Sitemap scan (SSE streaming) ──────────────────────────────────────────────

@app.post("/api/audit/sitemap")
async def audit_sitemap_route(body: SitemapRequest):
    sitemap_url = body.url.strip()
    scan_types  = body.scan_types
    max_urls    = min(body.max_urls, 100)

    async def generate():
        from core.browser import browser_context, fetch_bytes_from_page
        from core.auditors.pdf import audit_pdf
        from core.auditors.docx import audit_docx
        from core.auditors.page import audit_page

        def send(event: dict) -> str:
            return f"data: {json.dumps(event)}\n\n"

        yield send({"type": "log", "level": "info",
                    "message": f"Fetching sitemap: {sitemap_url}"})

        urls = await asyncio.to_thread(_extract_sitemap_urls, sitemap_url)

        if not urls:
            yield send({"type": "error",
                        "message": "No URLs found in sitemap. Check the URL is a valid sitemap.xml."})
            return

        urls = urls[:max_urls]
        yield send({"type": "log", "level": "success",
                    "message": f"Found {len(urls)} URL(s). Starting scan..."})

        total_critical = total_warning = total_manual = scanned = 0

        for idx, url in enumerate(urls):
            yield send({"type": "progress", "current": idx + 1,
                        "total": len(urls), "url": url})
            yield send({"type": "log", "level": "info",
                        "message": f"[{idx + 1}/{len(urls)}] Scanning: {url}"})

            def _scan_url(target_url):
                page_findings = []
                page_summary  = {"critical": 0, "warning": 0, "manual": 0,
                                  "passes": 0, "total_issues": 0, "all_clear": True}

                with browser_context() as ctx:
                    bpage = ctx.new_page()
                    try:
                        bpage.goto(target_url, timeout=30000, wait_until="networkidle")
                        bpage.wait_for_timeout(1000)
                    except Exception as nav_err:
                        return page_findings, page_summary, str(nav_err)

                    if "page" in scan_types:
                        try:
                            result = audit_page(target_url, page=bpage)
                            for f in result.findings:
                                page_findings.append(f.to_dict() if hasattr(f, "to_dict") else f)
                            s = result.summary
                            page_summary["critical"] += s.critical
                            page_summary["warning"]  += s.warning
                            page_summary["manual"]   += s.manual
                            page_summary["passes"]   += s.passes
                        except Exception:
                            pass

                    if "pdf" in scan_types:
                        for pdf_url in _find_linked_pdfs(bpage, target_url):
                            try:
                                pdf_bytes = fetch_bytes_from_page(bpage, pdf_url)
                                result = audit_pdf(pdf_bytes, source_label=pdf_url.split("/")[-1])
                                for f in result.findings:
                                    fd = f.to_dict() if hasattr(f, "to_dict") else f
                                    fd["description"] = f"[PDF] {fd['description']}"
                                    page_findings.append(fd)
                                s = result.summary
                                page_summary["critical"] += s.critical
                                page_summary["warning"]  += s.warning
                                page_summary["manual"]   += s.manual
                            except Exception:
                                pass

                    if "docx" in scan_types:
                        for docx_url in _find_linked_docx(bpage, target_url):
                            try:
                                docx_bytes = fetch_bytes_from_page(bpage, docx_url)
                                result = audit_docx(docx_bytes, source_label=docx_url.split("/")[-1])
                                for f in result.findings:
                                    fd = f.to_dict() if hasattr(f, "to_dict") else f
                                    fd["description"] = f"[DOCX] {fd['description']}"
                                    page_findings.append(fd)
                                s = result.summary
                                page_summary["critical"] += s.critical
                                page_summary["warning"]  += s.warning
                                page_summary["manual"]   += s.manual
                            except Exception:
                                pass

                    bpage.close()

                return page_findings, page_summary, None

            try:
                findings, summary, nav_error = await asyncio.to_thread(_scan_url, url)
            except Exception as e:
                yield send({"type": "log", "level": "error",
                            "message": f"  Error: {str(e)[:80]}"})
                continue

            if nav_error:
                yield send({"type": "log", "level": "warning",
                            "message": f"  Could not load page: {nav_error[:80]}"})
                continue

            scanned += 1
            total_critical += summary["critical"]
            total_warning  += summary["warning"]
            total_manual   += summary["manual"]

            issue_count = summary["critical"] + summary["warning"] + summary["manual"]
            summary["total_issues"] = issue_count
            summary["all_clear"]    = issue_count == 0

            level = "warning" if issue_count > 0 else "success"
            msg   = f"  Found {issue_count} issue(s)" if issue_count > 0 else "  No issues found"
            yield send({"type": "log", "level": level, "message": msg})

            yield send({
                "type": "result",
                "url": url,
                "result": {
                    "source_type":  "page",
                    "source_label": url,
                    "findings":     findings,
                    "summary":      summary,
                    "metadata":     {},
                    "error":        None,
                },
            })

        yield send({
            "type": "complete",
            "summary": {
                "total_urls":   len(urls),
                "scanned_urls": scanned,
                "critical":     total_critical,
                "warning":      total_warning,
                "manual":       total_manual,
                "total_issues": total_critical + total_warning + total_manual,
            },
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Export ────────────────────────────────────────────────────────────────────

@app.post("/api/export")
async def export_route(body: ExportRequest):
    fmt       = body.format.lower()
    results   = body.results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == "csv":
        return _export_csv(results, timestamp)
    elif fmt == "pdf":
        return await asyncio.to_thread(_export_pdf_report, results, timestamp)
    else:
        content = json.dumps(results, indent=2).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=accessscan-report-{timestamp}.json"},
        )


# ── Export helpers ────────────────────────────────────────────────────────────

def _export_csv(results: list[dict], timestamp: str) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Source", "Type", "Critical", "Warning", "Manual",
                     "Tier", "Criterion", "WCAG Level", "Description", "Fix"])
    for r in results:
        summary = r.get("summary", {})
        source  = r.get("source_label", r.get("url", "Unknown"))
        for f in r.get("findings", []):
            if f.get("tier") == "pass":
                continue
            writer.writerow([
                source, r.get("source_type", ""),
                summary.get("critical", 0), summary.get("warning", 0), summary.get("manual", 0),
                f.get("tier", ""), f.get("criterion", ""), f.get("wcag_level", ""),
                f.get("description", ""), f.get("fix_hint", ""),
            ])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=accessscan-report-{timestamp}.csv"},
    )


def _export_pdf_report(results: list[dict], timestamp: str) -> StreamingResponse:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc    = SimpleDocTemplate(buffer, pagesize=letter,
                               rightMargin=72, leftMargin=72,
                               topMargin=72, bottomMargin=72)
    styles = getSampleStyleSheet()

    title_style   = ParagraphStyle("Title", parent=styles["Heading1"],
                                   fontSize=20, spaceAfter=6,
                                   textColor=colors.HexColor("#005035"))
    h2_style      = ParagraphStyle("H2", parent=styles["Heading2"],
                                   fontSize=13, spaceAfter=6,
                                   textColor=colors.HexColor("#003d28"))
    meta_style    = ParagraphStyle("Meta", parent=styles["Normal"],
                                   fontSize=9, textColor=colors.HexColor("#64748b"))
    finding_style = ParagraphStyle("Finding", parent=styles["Normal"],
                                   fontSize=9, leftIndent=16, spaceAfter=4)
    fix_style     = ParagraphStyle("Fix", parent=styles["Normal"],
                                   fontSize=9, leftIndent=32, spaceAfter=8,
                                   textColor=colors.HexColor("#166534"))

    story = []
    story.append(Paragraph("AccessScan Accessibility Report", title_style))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
        meta_style,
    ))
    story.append(Spacer(1, 0.15 * inch))

    total_c = sum(r.get("summary", {}).get("critical", 0) for r in results)
    total_w = sum(r.get("summary", {}).get("warning", 0) for r in results)
    total_m = sum(r.get("summary", {}).get("manual", 0) for r in results)

    summary_data  = [["Items scanned", "Critical", "Warning", "Manual Review"],
                     [str(len(results)), str(total_c), str(total_w), str(total_m)]]
    summary_table = Table(summary_data, colWidths=[1.5 * inch] * 4)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#005035")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("BACKGROUND",    (1, 1), (1, 1),   colors.HexColor("#fee2e2")),
        ("BACKGROUND",    (2, 1), (2, 1),   colors.HexColor("#fef9c3")),
        ("BACKGROUND",    (3, 1), (3, 1),   colors.HexColor("#dbeafe")),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE",      (0, 0), (-1, -1), 10),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.3 * inch))

    for idx, r in enumerate(results):
        source      = r.get("source_label", r.get("url", "Unknown"))
        source_type = r.get("source_type", "").upper()
        summary     = r.get("summary", {})
        findings    = [f for f in r.get("findings", []) if f.get("tier") != "pass"]

        story.append(Paragraph(f"{idx + 1}. [{source_type}] {source}", h2_style))
        story.append(Paragraph(
            f"Critical: {summary.get('critical', 0)}  |  "
            f"Warning: {summary.get('warning', 0)}  |  "
            f"Manual: {summary.get('manual', 0)}",
            meta_style,
        ))
        story.append(Spacer(1, 0.08 * inch))

        if not findings:
            story.append(Paragraph("No accessibility issues found.", finding_style))
        else:
            for f in findings:
                tier      = f.get("tier", "")
                criterion = f.get("criterion", "")
                label     = f" [{criterion}]" if criterion else ""
                story.append(Paragraph(
                    f"<b>{tier.upper()}{label}:</b> {f.get('description', '')}",
                    finding_style,
                ))
                fix = f.get("fix_hint", "")
                if fix:
                    story.append(Paragraph(f"Fix: {fix}", fix_style))

        story.append(Spacer(1, 0.2 * inch))
        if (idx + 1) % 4 == 0 and (idx + 1) < len(results):
            story.append(PageBreak())

    doc.build(story)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=accessscan-report-{timestamp}.pdf"},
    )


# ── Shared utilities ──────────────────────────────────────────────────────────

def _find_linked_pdfs(page, base_url: str) -> list[str]:
    try:
        hrefs = page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                       .map(a => a.href)
                       .filter(h => h.toLowerCase().endsWith('.pdf'))
        """)
        return [urljoin(base_url, h) for h in (hrefs or []) if h]
    except Exception:
        return []


def _find_linked_docx(page, base_url: str) -> list[str]:
    try:
        hrefs = page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                       .map(a => a.href)
                       .filter(h => h.toLowerCase().endsWith('.docx'))
        """)
        return [urljoin(base_url, h) for h in (hrefs or []) if h]
    except Exception:
        return []


def _extract_sitemap_urls(sitemap_url: str) -> list[str]:
    try:
        resp = requests.get(sitemap_url, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns   = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [loc.text for loc in root.findall(".//ns:loc", ns) if loc.text]
        if not urls:
            urls = [loc.text for loc in root.findall(".//loc") if loc.text]
        return urls
    except Exception:
        return []


def _empty_summary() -> dict:
    return {"critical": 0, "warning": 0, "manual": 0,
            "passes": 0, "total_issues": 0, "all_clear": True}


def _combine_summaries(results: list[dict]) -> dict:
    combined = _empty_summary()
    for r in results:
        s = r.get("summary", {})
        combined["critical"] += s.get("critical", 0)
        combined["warning"]  += s.get("warning", 0)
        combined["manual"]   += s.get("manual", 0)
        combined["passes"]   += s.get("passes", 0)
    combined["total_issues"] = combined["critical"] + combined["warning"] + combined["manual"]
    combined["all_clear"]    = combined["total_issues"] == 0
    return combined


def get_embeds_from_page(page, url: str) -> list[dict]:
    """Extract embed elements with runtime metadata from a live page."""
    embeds     = []
    page_title = page.title()
    page_h1    = ""
    try:
        h1 = page.query_selector("h1")
        if h1:
            page_h1 = h1.inner_text()
    except Exception:
        pass

    for frame in page.frames[1:]:
        try:
            el = frame.frame_element()
            if not el:
                continue
            snippet  = el.evaluate("el => el.outerHTML")
            src      = el.get_attribute("src") or ""
            box      = el.bounding_box() or {"width": 0, "height": 0}
            interactive_count = 0
            try:
                interactive_count = frame.evaluate(
                    "() => document.querySelectorAll('a,button,input,select,textarea,[tabindex=\"0\"]').length"
                )
            except Exception:
                pass
            embeds.append({
                "snippet": snippet, "src": src,
                "frame_url": frame.url, "page_url": url,
                "is_visible": el.is_visible(),
                "width": box["width"], "height": box["height"],
                "aria_hidden": el.get_attribute("aria-hidden"),
                "tabindex": el.get_attribute("tabindex"),
                "page_title": page_title, "page_h1": page_h1,
                "interactive_count": interactive_count,
                "element_type": "iframe", "is_duplicate": False,
            })
        except Exception:
            pass

    for tag in ("video", "audio", "object", "embed"):
        for el in page.query_selector_all(tag):
            try:
                snippet = el.evaluate("el => el.outerHTML")
                src     = el.get_attribute("src") or el.get_attribute("data") or ""
                box     = el.bounding_box() or {"width": 0, "height": 0}
                embeds.append({
                    "snippet": snippet, "src": src, "page_url": url,
                    "is_visible": el.is_visible(),
                    "width": box["width"], "height": box["height"],
                    "aria_hidden": el.get_attribute("aria-hidden"),
                    "tabindex": el.get_attribute("tabindex"),
                    "page_title": page_title, "page_h1": page_h1,
                    "interactive_count": 0,
                    "element_type": tag, "is_duplicate": False,
                })
            except Exception:
                pass

    return embeds