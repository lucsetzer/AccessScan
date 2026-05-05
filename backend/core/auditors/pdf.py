"""
pdf.py — AccessScan PDF accessibility auditor.

Checks (all mapped to WCAG 2.2 / PDF/UA-1 / Section 508):
  1.  Document title (WCAG 2.4.2)
  2.  Document language (WCAG 3.1.1)
  3.  Tagged PDF / PDF/UA (PDF/UA-1)
  4.  Heading structure — uses tag tree, not TOC (WCAG 1.3.1)
  5.  Table headers (WCAG 1.3.1)
  6.  Image alt text — inspects actual Figure tags (WCAG 1.1.1)
  7.  Form field labels (WCAG 3.3.2 / 4.1.2)
  8.  Reading order advisory (WCAG 1.3.2)
  9.  Link text — checks for vague text (WCAG 2.4.4)
  10. Color contrast advisory (WCAG 1.4.3) — manual, cannot be automated
  11. Bookmark / navigation structure (WCAG 2.4.1)
"""
from __future__ import annotations

import io
import re
import struct
from typing import Any

import fitz          # PyMuPDF
import pdfplumber

from core.schema import AuditResult, Finding, Tier, make_finding

# Vague link text patterns
VAGUE_LINK_PATTERNS = re.compile(
    r"^(click here|here|more|read more|link|this link|learn more|details|info|"
    r"download|view|open|see more|go|continue|next|previous)$",
    re.IGNORECASE,
)


def audit_pdf(pdf_bytes: bytes, source_label: str = "PDF Document") -> AuditResult:
    """
    Run a full accessibility audit on a PDF.
    Returns an AuditResult with all findings.
    """
    findings: list[Finding] = []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        raw_meta = doc.metadata or {}

        # ── 1. Document Title (WCAG 2.4.2) ───────────────────────────────────
        title = raw_meta.get("title", "").strip()
        if not title:
            findings.append(make_finding(
                Tier.CRITICAL,
                "Document title is missing from metadata.",
                "In Word: File → Properties → Summary → Title. "
                "In Acrobat: File → Properties → Description → Title.",
                "WCAG 2.4.2",
            ))
        else:
            findings.append(make_finding(
                Tier.PASS,
                f'Document title is set: "{title}"',
                "",
                "WCAG 2.4.2",
            ))

        # ── 2. Document Language (WCAG 3.1.1) ────────────────────────────────
        # Correct PyMuPDF approach: read the catalog xref directly
        doc_lang = _get_pdf_language(doc)
        if not doc_lang:
            findings.append(make_finding(
                Tier.CRITICAL,
                "Document language is not declared. Screen readers cannot "
                "determine the correct pronunciation and reading rules.",
                "In Word: File → Options → Language → set editing language. "
                "Re-export as PDF. In Acrobat: File → Properties → Advanced → Language.",
                "WCAG 3.1.1",
            ))
        else:
            findings.append(make_finding(
                Tier.PASS,
                f"Document language is declared: {doc_lang}",
                "",
                "WCAG 3.1.1",
            ))

        # ── 3. Tagged PDF / PDF/UA (PDF/UA-1) ────────────────────────────────
        is_tagged = _is_tagged_pdf(doc)
        if not is_tagged:
            findings.append(make_finding(
                Tier.CRITICAL,
                "PDF is not tagged. Screen readers cannot determine reading "
                "order, and structural elements like headings and lists are invisible.",
                "Re-export from source with 'Tagged PDF' enabled. "
                "In Word: Save As PDF → Options → check 'Document structure tags for accessibility'. "
                "In Acrobat: Tools → Accessibility → Add Tags to Document.",
                "PDF/UA-1",
            ))
        else:
            findings.append(make_finding(
                Tier.PASS,
                "PDF is tagged — structural reading order is available to screen readers.",
                "",
                "PDF/UA-1",
            ))

        # ── 4. Heading Structure (WCAG 1.3.1) ────────────────────────────────
        # Uses the PDF tag tree, not get_toc() which only reflects bookmarks
        heading_findings = _check_heading_structure(doc, is_tagged)
        findings.extend(heading_findings)

        # ── 5. Image Alt Text (WCAG 1.1.1) ───────────────────────────────────
        # Actually inspects Figure tags in the structure tree
        image_findings, image_count = _check_image_alt_text(doc, pdf_bytes)
        findings.extend(image_findings)

        # ── 6. Table Headers (WCAG 1.3.1) ────────────────────────────────────
        table_findings = _check_tables(pdf_bytes)
        findings.extend(table_findings)

        # ── 7. Form Fields (WCAG 3.3.2 / 4.1.2) ─────────────────────────────
        form_findings, form_count = _check_form_fields(doc)
        findings.extend(form_findings)

        # ── 8. Link Text (WCAG 2.4.4) ────────────────────────────────────────
        link_findings = _check_link_text(doc)
        findings.extend(link_findings)

        # ── 9. Bookmark Navigation (WCAG 2.4.1) ──────────────────────────────
        page_count = len(doc)
        if page_count > 3:
            toc = doc.get_toc()
            if not toc:
                findings.append(make_finding(
                    Tier.WARNING,
                    f"No bookmarks found in this {page_count}-page document. "
                    "Users cannot navigate between sections efficiently.",
                    "Add bookmarks in Acrobat: View → Navigation Panels → Bookmarks. "
                    "Or re-export from source with heading styles — most tools auto-generate bookmarks.",
                    "WCAG 2.4.1",
                ))
            else:
                findings.append(make_finding(
                    Tier.PASS,
                    f"Document has {len(toc)} bookmark(s) for navigation.",
                    "",
                    "WCAG 2.4.1",
                ))

        # ── 10. Reading Order Advisory (WCAG 1.3.2) ──────────────────────────
        if is_tagged:
            findings.append(make_finding(
                Tier.MANUAL,
                "Reading order must be manually verified even in tagged PDFs. "
                "The tag order may not match the visual layout (common in multi-column docs).",
                "In Acrobat: View → Navigation Panels → Tags. "
                "Read through the tag tree and confirm it matches the intended reading order. "
                "Use the Reading Order tool (Tools → Accessibility → Reading Order) to fix issues.",
                "WCAG 1.3.2",
            ))

        # ── 11. Color Contrast Advisory (WCAG 1.4.3) ─────────────────────────
        findings.append(make_finding(
            Tier.MANUAL,
            "Color contrast cannot be fully automated for PDFs. "
            "All text must meet at least 4.5:1 contrast ratio against its background "
            "(3:1 for large text — 18pt or 14pt bold).",
            "Use WebAIM Contrast Checker (webaim.org/resources/contrastchecker/) "
            "to verify text colors. Check especially low-contrast elements like "
            "grey text on white, or text over images.",
            "WCAG 1.4.3",
        ))

        doc.close()

        return AuditResult(
            source_type="pdf",
            source_label=source_label,
            findings=findings,
            metadata={
                "title": title,
                "author": raw_meta.get("author", ""),
                "pages": page_count,
                "is_tagged": is_tagged,
                "language": doc_lang,
                "image_count": image_count,
                "form_field_count": form_count,
            },
        )

    except Exception as e:
        return AuditResult(
            source_type="pdf",
            source_label=source_label,
            findings=[],
            error=f"PDF audit failed: {str(e)}",
        )


# ── Private helpers ───────────────────────────────────────────────────────────

def _get_pdf_language(doc: fitz.Document) -> str:
    """
    Correctly read the document language from the PDF catalog.
    PyMuPDF exposes this via the trailer/catalog xref — not via a method call.
    """
    try:
        catalog_xref = doc.pdf_catalog()
        # pdf_catalog() returns the xref number of the catalog dictionary
        # We read its keys using xref_get_key
        lang = doc.xref_get_key(catalog_xref, "Lang")
        if lang and lang[0] != "null":
            # Returns a tuple: (type, value) — value may include surrounding parens
            raw = lang[1].strip("()")
            return raw
    except Exception:
        pass

    # Fallback: check XMP metadata stream
    try:
        xmp = doc.get_xml_metadata()
        if xmp:
            match = re.search(r'dc:language[^>]*>([a-zA-Z-]{2,10})', xmp)
            if match:
                return match.group(1)
    except Exception:
        pass

    return ""


def _is_tagged_pdf(doc: fitz.Document) -> bool:
    """Check if the PDF has MarkInfo/Marked = true (tagged PDF)."""
    try:
        catalog_xref = doc.pdf_catalog()
        mark_info = doc.xref_get_key(catalog_xref, "MarkInfo")
        if mark_info and mark_info[0] != "null":
            return "true" in mark_info[1].lower()
    except Exception:
        pass
    return False


def _check_heading_structure(doc: fitz.Document, is_tagged: bool) -> list[Finding]:
    """
    Check heading structure using the PDF tag tree (not TOC/bookmarks).
    This correctly identifies H1/H2/H3 tags in the structure tree.
    """
    findings = []

    if not is_tagged:
        # Already flagged as untagged — don't double-report
        return findings

    try:
        # Walk the structure tree looking for heading tags
        headings = []
        _walk_structure_tree(doc, headings)

        if not headings:
            findings.append(make_finding(
                Tier.WARNING,
                "No heading tags found in the document structure tree. "
                "Screen readers cannot navigate by headings.",
                "Apply heading styles (Heading 1, Heading 2, etc.) in your source document "
                "before exporting to PDF. Do not use bold/large text as a visual substitute for headings.",
                "WCAG 1.3.1",
                "H42",
            ))
            return findings

        # Check hierarchy — no level skipping
        prev_level = 0
        skips = []
        for level, text in headings:
            if prev_level > 0 and level > prev_level + 1:
                skips.append((prev_level, level, text[:40]))
            prev_level = level

        if skips:
            for (from_level, to_level, text) in skips[:3]:  # cap at 3 examples
                findings.append(make_finding(
                    Tier.WARNING,
                    f"Heading level skipped: H{from_level} jumps to H{to_level} "
                    f'(near: "{text}"). '
                    "This breaks navigation for screen reader users.",
                    f"Change the heading to H{from_level + 1} or add a missing "
                    f"H{from_level + 1} heading before it.",
                    "WCAG 1.3.1",
                    "G141",
                ))
        else:
            findings.append(make_finding(
                Tier.PASS,
                f"Heading structure is valid — {len(headings)} heading(s) in correct hierarchy.",
                "",
                "WCAG 1.3.1",
            ))

        # Check that document starts with H1
        if headings and headings[0][0] != 1:
            findings.append(make_finding(
                Tier.WARNING,
                f"Document does not start with an H1 heading (first heading is H{headings[0][0]}). "
                "Screen readers expect a top-level H1 as the document title.",
                "Add an H1 heading as the first heading in the document.",
                "WCAG 1.3.1",
                "G141",
            ))

    except Exception as e:
        findings.append(make_finding(
            Tier.MANUAL,
            "Heading structure could not be automatically verified.",
            "Manually inspect the PDF tag tree in Acrobat: View → Navigation Panels → Tags.",
            "WCAG 1.3.1",
        ))

    return findings


def _walk_structure_tree(doc: fitz.Document, headings: list) -> None:
    """Walk the PDF structure tree and collect heading tags."""
    HEADING_TAGS = {"H", "H1", "H2", "H3", "H4", "H5", "H6"}

    try:
        # Use PyMuPDF's PDF structure tree access
        # get_pdf_str_tree returns a nested dict representation
        trailer = doc.pdf_trailer()
        catalog_xref = doc.pdf_catalog()

        # Try to access StructTreeRoot
        struct_root = doc.xref_get_key(catalog_xref, "StructTreeRoot")
        if not struct_root or struct_root[0] == "null":
            return

        # Walk using xref traversal
        _traverse_struct_node(doc, struct_root[1], headings, depth=0)
    except Exception:
        pass


def _traverse_struct_node(doc: fitz.Document, node_ref: str, headings: list, depth: int) -> None:
    """Recursively traverse a structure tree node."""
    if depth > 50:  # Guard against infinite recursion
        return
    try:
        # Resolve xref reference
        xref_match = re.match(r"(\d+)\s+\d+\s+R", node_ref.strip())
        if not xref_match:
            return
        xref = int(xref_match.group(1))

        tag_type = doc.xref_get_key(xref, "S")
        if tag_type and tag_type[0] != "null":
            tag_name = tag_type[1].strip("/")
            if tag_name in {"H1", "H2", "H3", "H4", "H5", "H6"}:
                level = int(tag_name[1])
                # Try to get text content
                alt_text = doc.xref_get_key(xref, "Alt")
                title_text = doc.xref_get_key(xref, "T")
                label = ""
                if title_text and title_text[0] != "null":
                    label = title_text[1].strip("()")
                headings.append((level, label))
            elif tag_name == "H":
                headings.append((1, ""))

        # Recurse into children
        kids = doc.xref_get_key(xref, "K")
        if kids and kids[0] != "null":
            kid_str = kids[1].strip()
            # Parse array of references
            refs = re.findall(r"\d+\s+\d+\s+R", kid_str)
            for ref in refs:
                _traverse_struct_node(doc, ref, headings, depth + 1)
    except Exception:
        pass


def _check_image_alt_text(doc: fitz.Document, pdf_bytes: bytes) -> tuple[list[Finding], int]:
    """
    Check Figure tags in the structure tree for Alt text.
    Falls back to counting images via pdfplumber if tree walk fails.
    """
    findings = []
    images_total = 0
    images_missing_alt = 0

    try:
        catalog_xref = doc.pdf_catalog()
        struct_root = doc.xref_get_key(catalog_xref, "StructTreeRoot")

        if struct_root and struct_root[0] != "null":
            figure_results = []
            _find_figures(doc, struct_root[1], figure_results, depth=0)
            images_total = len(figure_results)

            for has_alt, snippet in figure_results:
                if not has_alt:
                    images_missing_alt += 1

            if images_total > 0:
                if images_missing_alt > 0:
                    findings.append(make_finding(
                        Tier.CRITICAL,
                        f"{images_missing_alt} of {images_total} image(s) are missing "
                        "alternative text. Screen reader users will not know what these images show.",
                        "In Acrobat: Open the Tags panel → find each <Figure> tag → "
                        "right-click → Properties → Alt Text tab → add a description. "
                        "In Word: right-click each image → Edit Alt Text.",
                        "WCAG 1.1.1",
                        "H37",
                    ))
                else:
                    findings.append(make_finding(
                        Tier.PASS,
                        f"All {images_total} image(s) have alternative text.",
                        "",
                        "WCAG 1.1.1",
                    ))
            return findings, images_total

    except Exception:
        pass

    # Fallback: count images via pdfplumber, flag as manual
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                images_total += len(page.images)
    except Exception:
        pass

    if images_total > 0:
        findings.append(make_finding(
            Tier.MANUAL,
            f"Found {images_total} image(s). Alt text could not be automatically verified "
            "(PDF may not be fully tagged).",
            "In Acrobat: Tags panel → find each <Figure> tag → right-click → Properties → "
            "Alt Text → add a description. Decorative images should have empty alt text and "
            "be marked as Artifact.",
            "WCAG 1.1.1",
            "H37",
        ))

    return findings, images_total


def _find_figures(doc: fitz.Document, node_ref: str, results: list, depth: int) -> None:
    """Find all Figure tags and check for Alt text."""
    if depth > 50:
        return
    try:
        xref_match = re.match(r"(\d+)\s+\d+\s+R", node_ref.strip())
        if not xref_match:
            return
        xref = int(xref_match.group(1))

        tag_type = doc.xref_get_key(xref, "S")
        if tag_type and tag_type[0] != "null":
            tag_name = tag_type[1].strip("/")
            if tag_name == "Figure":
                alt = doc.xref_get_key(xref, "Alt")
                has_alt = alt and alt[0] != "null" and alt[1].strip("()") != ""
                results.append((has_alt, tag_name))

        kids = doc.xref_get_key(xref, "K")
        if kids and kids[0] != "null":
            refs = re.findall(r"\d+\s+\d+\s+R", kids[1])
            for ref in refs:
                _find_figures(doc, ref, results, depth + 1)
    except Exception:
        pass


def _check_tables(pdf_bytes: bytes) -> list[Finding]:
    """Check tables for header rows using pdfplumber."""
    findings = []
    tables_checked = 0
    tables_missing_headers = 0

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    tables_checked += 1
                    first_row = table[0]

                    # A header row typically has content in most cells
                    # and the second row should have different content
                    has_content = any(cell and str(cell).strip() for cell in first_row)
                    if not has_content:
                        tables_missing_headers += 1
                        if tables_missing_headers <= 3:
                            findings.append(make_finding(
                                Tier.WARNING,
                                f"Table on page {page_num} appears to have no header row. "
                                "Screen readers cannot identify column meanings.",
                                "In your source document, designate the first row as a header row. "
                                "In Word: click in the table → Table Design → check 'Header Row'. "
                                "In Acrobat: Tags panel → Table Editor → mark TH cells.",
                                "WCAG 1.3.1",
                                "H51",
                                location=f"Page {page_num}",
                            ))

        if tables_checked > 0 and tables_missing_headers == 0:
            findings.append(make_finding(
                Tier.PASS,
                f"All {tables_checked} table(s) appear to have header rows.",
                "",
                "WCAG 1.3.1",
            ))

    except Exception:
        pass

    return findings


def _check_form_fields(doc: fitz.Document) -> tuple[list[Finding], int]:
    """Check form fields for labels/tooltips."""
    findings = []
    field_count = 0
    unlabeled = 0

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            widgets = page.widgets()
            if not widgets:
                continue
            for widget in widgets:
                field_count += 1
                label = (widget.field_label or "").strip()
                name = (widget.field_name or "").strip()
                # Reject generic auto-names like "Text1", "Field1"
                has_meaningful_name = name and not re.match(
                    r"^(text|field|checkbox|button|combo|list)\d+$", name, re.IGNORECASE
                )
                if not label and not has_meaningful_name:
                    unlabeled += 1
                    if unlabeled <= 3:
                        findings.append(make_finding(
                            Tier.WARNING,
                            f"Form field on page {page_num + 1} has no label or tooltip. "
                            "Screen readers cannot identify its purpose.",
                            "In Acrobat: Forms → Edit → right-click the field → Properties → "
                            "General tab → add a descriptive Tooltip.",
                            "WCAG 3.3.2",
                            "H44",
                            location=f"Page {page_num + 1}",
                        ))

        if field_count > 0 and unlabeled == 0:
            findings.append(make_finding(
                Tier.PASS,
                f"All {field_count} form field(s) have labels.",
                "",
                "WCAG 3.3.2",
            ))

    except Exception:
        pass

    return findings, field_count


def _check_link_text(doc: fitz.Document) -> list[Finding]:
    """Check for vague link text like 'click here', 'here', 'more'."""
    findings = []
    vague_count = 0

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            links = page.get_links()
            for link in links:
                if link.get("kind") != fitz.LINK_URI:
                    continue
                # Get text in the link rect
                rect = link.get("from")
                if rect:
                    text = page.get_text("text", clip=rect).strip()
                    if text and VAGUE_LINK_PATTERNS.match(text):
                        vague_count += 1
                        if vague_count <= 3:
                            findings.append(make_finding(
                                Tier.WARNING,
                                f'Link text "{text}" on page {page_num + 1} is not descriptive. '
                                "Screen reader users navigating by links cannot determine the destination.",
                                "Replace vague link text with a description of the destination, "
                                'e.g. "Download the 2024 Annual Report" instead of "click here".',
                                "WCAG 2.4.4",
                                "H30",
                                location=f"Page {page_num + 1}",
                            ))
    except Exception:
        pass

    return findings