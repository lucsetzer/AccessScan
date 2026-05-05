"""
schema.py — Single shared data model for all AccessScan auditors.

Every auditor (embed, pdf, docx, page) must return Finding and AuditResult
objects. No exceptions. This is what prevents tier/format inconsistencies.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# ── Tier (severity) ───────────────────────────────────────────────────────────

class Tier(str, Enum):
    """
    Severity tiers — always lowercase strings so JSON is consistent.
    Frontend can display these however it likes, but the values never change.
    """
    CRITICAL = "critical"   # Blocks access for some users. Must fix. (WCAG A/AA fail)
    WARNING  = "warning"    # Degrades experience. Should fix.
    MANUAL   = "manual"     # Cannot be automated. Requires human review.
    PASS     = "pass"       # Explicitly checked and passed. Shown in verbose mode.


# ── WCAG level ────────────────────────────────────────────────────────────────

class WCAGLevel(str, Enum):
    A   = "A"
    AA  = "AA"
    AAA = "AAA"
    NA  = "N/A"   # For PDF/UA or Section 508 criteria outside WCAG


# ── Finding ───────────────────────────────────────────────────────────────────

@dataclass
class Finding:
    """
    One accessibility issue (or pass) from any auditor.
    All fields are plain strings so they serialize to JSON cleanly.
    """
    tier: str                        # Tier enum value: "critical" | "warning" | "manual" | "pass"
    description: str                 # Plain-English description of the issue
    fix_hint: str                    # Plain-English fix instruction
    criterion: str = ""              # e.g. "WCAG 1.1.1" or "PDF/UA-1"
    criterion_name: str = ""         # e.g. "Non-text Content"
    wcag_level: str = ""             # "A" | "AA" | "AAA" | "N/A"
    wcag_url: str = ""               # Direct link to WCAG understanding doc
    technique: str = ""              # e.g. "H64", "G87", "ARIA14"
    location: Optional[str] = None   # e.g. "Page 3", "Table 2", element XPath
    element_snippet: Optional[str] = None  # Raw HTML/tag snippet if applicable

    def to_dict(self) -> dict:
        return asdict(self)


# ── Summary ───────────────────────────────────────────────────────────────────

@dataclass
class Summary:
    """Counts of findings by tier."""
    critical: int = 0
    warning:  int = 0
    manual:   int = 0
    passes:   int = 0

    @property
    def total_issues(self) -> int:
        return self.critical + self.warning + self.manual

    @property
    def all_clear(self) -> bool:
        return self.critical == 0 and self.warning == 0

    def to_dict(self) -> dict:
        return {
            "critical": self.critical,
            "warning":  self.warning,
            "manual":   self.manual,
            "passes":   self.passes,
            "total_issues": self.total_issues,
            "all_clear": self.all_clear,
        }


# ── AuditResult ───────────────────────────────────────────────────────────────

@dataclass
class AuditResult:
    """
    The complete output of any single audit (one file, one URL, one snippet).
    This is what every auditor returns. FastAPI routes serialize this to JSON.
    """
    source_type: str          # "pdf" | "docx" | "embed" | "page"
    source_label: str         # Filename, URL, or "HTML Snippet"
    findings: list[Finding] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # Source-specific extra info
    error: Optional[str] = None

    @property
    def summary(self) -> Summary:
        s = Summary()
        for f in self.findings:
            if f.tier == Tier.CRITICAL:
                s.critical += 1
            elif f.tier == Tier.WARNING:
                s.warning += 1
            elif f.tier == Tier.MANUAL:
                s.manual += 1
            elif f.tier == Tier.PASS:
                s.passes += 1
        return s

    def to_dict(self) -> dict:
        return {
            "source_type":  self.source_type,
            "source_label": self.source_label,
            "summary":      self.summary.to_dict(),
            "findings":     [f.to_dict() for f in self.findings],
            "metadata":     self.metadata,
            "error":        self.error,
        }


# ── SitemapResult ─────────────────────────────────────────────────────────────

@dataclass
class SitemapResult:
    """
    Aggregated result for a full sitemap scan.
    Contains one AuditResult per URL scanned.
    """
    sitemap_url: str
    page_results: list[dict] = field(default_factory=list)  # list of AuditResult.to_dict()
    total_urls: int = 0
    scanned_urls: int = 0
    error: Optional[str] = None

    @property
    def combined_summary(self) -> Summary:
        s = Summary()
        for page in self.page_results:
            page_summary = page.get("summary", {})
            s.critical += page_summary.get("critical", 0)
            s.warning  += page_summary.get("warning", 0)
            s.manual   += page_summary.get("manual", 0)
            s.passes   += page_summary.get("passes", 0)
        return s

    def to_dict(self) -> dict:
        return {
            "sitemap_url":       self.sitemap_url,
            "total_urls":        self.total_urls,
            "scanned_urls":      self.scanned_urls,
            "combined_summary":  self.combined_summary.to_dict(),
            "page_results":      self.page_results,
            "error":             self.error,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

WCAG_BASE = "https://www.w3.org/WAI/WCAG22/Understanding/"

CRITERIA: dict[str, dict] = {
    "WCAG 1.1.1": {"name": "Non-text Content",                    "level": "A",   "slug": "non-text-content"},
    "WCAG 1.2.1": {"name": "Audio-only and Video-only",           "level": "A",   "slug": "audio-only-and-video-only-prerecorded"},
    "WCAG 1.2.2": {"name": "Captions (Prerecorded)",              "level": "A",   "slug": "captions-prerecorded"},
    "WCAG 1.2.3": {"name": "Audio Description or Media Alt",      "level": "A",   "slug": "audio-description-or-media-alternative-prerecorded"},
    "WCAG 1.2.4": {"name": "Captions (Live)",                     "level": "AA",  "slug": "captions-live"},
    "WCAG 1.2.5": {"name": "Audio Description (Prerecorded)",     "level": "AA",  "slug": "audio-description-prerecorded"},
    "WCAG 1.3.1": {"name": "Info and Relationships",              "level": "A",   "slug": "info-and-relationships"},
    "WCAG 1.3.2": {"name": "Meaningful Sequence",                 "level": "A",   "slug": "meaningful-sequence"},
    "WCAG 1.4.1": {"name": "Use of Color",                        "level": "A",   "slug": "use-of-color"},
    "WCAG 1.4.3": {"name": "Contrast (Minimum)",                  "level": "AA",  "slug": "contrast-minimum"},
    "WCAG 2.1.1": {"name": "Keyboard",                            "level": "A",   "slug": "keyboard"},
    "WCAG 2.4.1": {"name": "Bypass Blocks",                       "level": "A",   "slug": "bypass-blocks"},
    "WCAG 2.4.2": {"name": "Page Titled",                         "level": "A",   "slug": "page-titled"},
    "WCAG 2.4.4": {"name": "Link Purpose (In Context)",           "level": "A",   "slug": "link-purpose-in-context"},
    "WCAG 2.4.6": {"name": "Headings and Labels",                 "level": "AA",  "slug": "headings-and-labels"},
    "WCAG 3.1.1": {"name": "Language of Page",                    "level": "A",   "slug": "language-of-page"},
    "WCAG 3.3.2": {"name": "Labels or Instructions",              "level": "A",   "slug": "labels-or-instructions"},
    "WCAG 4.1.2": {"name": "Name, Role, Value",                   "level": "A",   "slug": "name-role-value"},
    "PDF/UA-1":   {"name": "PDF Accessibility (PDF/UA)",          "level": "N/A", "slug": None},
    "Section 508":{"name": "Section 508 Compliance",              "level": "N/A", "slug": None},
}


def make_finding(
    tier: Tier,
    description: str,
    fix_hint: str,
    criterion: str = "",
    technique: str = "",
    location: Optional[str] = None,
    element_snippet: Optional[str] = None,
) -> Finding:
    """
    Convenience constructor. Looks up criterion metadata automatically.
    Usage:
        make_finding(Tier.CRITICAL, "Missing alt text", "Add alt=...", "WCAG 1.1.1", "H37")
    """
    c = CRITERIA.get(criterion, {})
    slug = c.get("slug")
    return Finding(
        tier=tier.value,
        description=description,
        fix_hint=fix_hint,
        criterion=criterion,
        criterion_name=c.get("name", ""),
        wcag_level=c.get("level", ""),
        wcag_url=(WCAG_BASE + slug) if slug else "",
        technique=technique,
        location=location,
        element_snippet=element_snippet,
    )