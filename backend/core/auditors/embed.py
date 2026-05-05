"""
embed.py — AccessScan embed element accessibility auditor.

Supports: <iframe>, <object>, <embed>, <video>, <audio>

Checks (all mapped to WCAG 2.2):
  1.  Title / accessible name (WCAG 4.1.2)
  2.  Keyboard access — tabindex, controls (WCAG 2.1.1)
  3.  Captions track for video (WCAG 1.2.2)
  4.  Audio description track for video (WCAG 1.2.5)
  5.  Transcript advisory for audio (WCAG 1.2.1)
  6.  Autoplay warnings (WCAG 1.2.2 / 1.2.4)
  7.  Fallback content for <object> (WCAG 1.1.1)
  8.  Tracking pixel detection (WCAG 4.1.2)
  9.  aria-hidden + focusable conflict (WCAG 2.1.1)
  10. Title matches page title (WCAG 4.1.2)
"""
from __future__ import annotations

import copy
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from core.schema import AuditResult, Finding, Tier, make_finding

# Tags this auditor handles
SUPPORTED_TAGS = ("iframe", "object", "embed", "video", "audio")

# Generic titles that provide no useful information
GENERIC_TITLES = {
    "iframe", "frame", "embedded", "embed", "content", "widget",
    "banner", "ad", "advertisement", "untitled", "video", "audio",
    "object", "media", "player", "document", "page", "site",
}


def audit_embed(
    snippet: str,
    metadata: Optional[dict] = None,
    source_label: str = "HTML Snippet",
) -> list[AuditResult]:
    """
    Audit ALL supported embed elements found in a snippet or page HTML.

    Args:
        snippet:      Raw HTML string containing one or more embed elements.
        metadata:     Runtime data from browser_fetcher (visibility, dimensions,
                      aria state, etc.). Applied to the first element if present.
        source_label: Human-readable label for the source (URL or "HTML Snippet").

    Returns:
        List of AuditResult — one per element found.
        Empty list if no supported elements are found.
    """
    if not snippet or not snippet.strip():
        return []

    soup = BeautifulSoup(snippet.strip(), "lxml")
    results: list[AuditResult] = []

    # Collect all supported elements in document order
    elements: list[tuple[Tag, str]] = []
    for tag_name in SUPPORTED_TAGS:
        for el in soup.find_all(tag_name):
            elements.append((el, tag_name))

    if not elements:
        return []

    for i, (el, tag_name) in enumerate(elements):
        # Only apply metadata to the first element — metadata comes from the
        # browser and is scoped to one specific element at a time
        el_metadata = metadata if (i == 0 and metadata) else None

        findings = _audit_element(el, tag_name, el_metadata)

        # Generate fix code suggestions
        minimal_fix = _generate_minimal_fix(el, tag_name, findings)
        full_fix = _generate_full_fix(el, tag_name, findings)

        result = AuditResult(
            source_type="embed",
            source_label=source_label,
            findings=findings,
            metadata={
                "element_type": tag_name,
                "element_index": i + 1,
                "snippet": str(el),
                "minimal_fix": minimal_fix,
                "full_fix": full_fix,
                # Runtime metadata passthrough
                "is_visible": (el_metadata or {}).get("is_visible"),
                "width": (el_metadata or {}).get("width"),
                "height": (el_metadata or {}).get("height"),
                "dom_path": (el_metadata or {}).get("dom_path"),
                "src": el.get("src") or el.get("data") or "",
                "frame_url": (el_metadata or {}).get("frame_url"),
                "is_duplicate": (el_metadata or {}).get("is_duplicate", False),
                "duplicate_count": (el_metadata or {}).get("duplicate_count", 0),
                "original_index": (el_metadata or {}).get("original_index"),
            },
        )
        results.append(result)

    return results


# ── Element auditors ──────────────────────────────────────────────────────────

def _audit_element(
    el: Tag,
    tag_name: str,
    metadata: Optional[dict],
) -> list[Finding]:
    """Dispatch to the correct element auditor and apply metadata heuristics."""

    dispatch = {
        "iframe": _audit_iframe,
        "object": _audit_object,
        "embed":  _audit_embed_tag,
        "video":  _audit_video,
        "audio":  _audit_audio,
    }

    findings = dispatch[tag_name](el)

    # Apply runtime metadata heuristics (only when we have browser data)
    if metadata:
        findings.extend(_apply_metadata_heuristics(el, tag_name, metadata, findings))

    return findings


def _audit_iframe(el: Tag) -> list[Finding]:
    findings = []
    title = (el.get("title") or "").strip()

    if not title:
        findings.append(make_finding(
            Tier.CRITICAL,
            "Missing title attribute. Screen readers announce iframes by their "
            "title — without one, users have no idea what this frame contains.",
            'Add title="[Descriptive purpose]" to the <iframe> tag. '
            'Example: title="Campus Map — embedded Google Maps".',
            "WCAG 4.1.2",
            "H64",
        ))
    elif _is_generic_title(title):
        findings.append(make_finding(
            Tier.WARNING,
            f'title="{title}" is too generic. It does not describe the specific '
            "content or purpose of this frame.",
            f'Replace title="{title}" with a specific description. '
            'Example: title="2025 Benefits Enrollment Form".',
            "WCAG 4.1.2",
            "H64",
        ))
    else:
        findings.append(make_finding(
            Tier.PASS,
            f'title="{title}" is present and descriptive.',
            "",
            "WCAG 4.1.2",
        ))

    # tabindex="-1" blocks keyboard entry into the frame
    tabindex = str(el.get("tabindex", "")).strip()
    aria_hidden = str(el.get("aria-hidden", "")).lower()

    if tabindex == "-1" and aria_hidden != "true":
        findings.append(make_finding(
            Tier.CRITICAL,
            'tabindex="-1" prevents keyboard users from accessing iframe content, '
            "but aria-hidden is not set. Keyboard users are blocked; screen reader "
            "users may still enter the frame.",
            'Either remove tabindex="-1" to allow keyboard access, OR add '
            'aria-hidden="true" to hide it from all assistive technology '
            "(only appropriate for decorative/tracking frames).",
            "WCAG 2.1.1",
            "G202",
        ))
    elif tabindex == "-1" and aria_hidden == "true":
        findings.append(make_finding(
            Tier.PASS,
            'Frame is hidden from assistive technology (aria-hidden="true" + '
            'tabindex="-1"). Appropriate only for decorative or tracking frames.',
            "",
            "WCAG 2.1.1",
        ))

    return findings


def _audit_object(el: Tag) -> list[Finding]:
    findings = []
    title = (el.get("title") or "").strip()

    if not title:
        findings.append(make_finding(
            Tier.CRITICAL,
            "Missing title attribute on <object>. Screen readers cannot "
            "identify the embedded content.",
            'Add title="[Descriptive label]" to the <object> tag.',
            "WCAG 4.1.2",
            "H27",
        ))
    elif _is_generic_title(title):
        findings.append(make_finding(
            Tier.WARNING,
            f'title="{title}" is too generic.',
            "Replace with a specific description of the embedded content.",
            "WCAG 4.1.2",
            "H27",
        ))
    else:
        findings.append(make_finding(
            Tier.PASS,
            f'title="{title}" is present and descriptive.',
            "",
            "WCAG 4.1.2",
        ))

    # Fallback content between <object> tags
    inner_text = el.get_text(strip=True)
    inner_html = el.decode_contents().strip()

    if not inner_text and not inner_html:
        findings.append(make_finding(
            Tier.CRITICAL,
            "No fallback content between <object> tags. If the plugin or "
            "media cannot load, users receive nothing.",
            "Add a text alternative or download link between the opening and "
            "closing <object> tags. Example: "
            '<p><a href="document.pdf">Download document (PDF)</a></p>',
            "WCAG 1.1.1",
            "H27",
        ))
    else:
        findings.append(make_finding(
            Tier.PASS,
            "Fallback content is present between <object> tags.",
            "",
            "WCAG 1.1.1",
        ))

    return findings


def _audit_embed_tag(el: Tag) -> list[Finding]:
    findings = []
    title = (el.get("title") or "").strip()

    if not title:
        findings.append(make_finding(
            Tier.CRITICAL,
            "Missing title attribute on <embed>. Screen readers cannot "
            "identify the embedded content.",
            'Add title="[Descriptive label]" to the <embed> tag.',
            "WCAG 4.1.2",
            "H64",
        ))
    elif _is_generic_title(title):
        findings.append(make_finding(
            Tier.WARNING,
            f'title="{title}" is too generic.',
            "Replace with a specific description of the embedded content.",
            "WCAG 4.1.2",
            "H64",
        ))
    else:
        findings.append(make_finding(
            Tier.PASS,
            f'title="{title}" is present and descriptive.',
            "",
            "WCAG 4.1.2",
        ))

    # <embed> is a void element — cannot have fallback content
    findings.append(make_finding(
        Tier.MANUAL,
        "<embed> cannot contain fallback content (it is a void element). "
        "If fallback is needed, use <object> instead.",
        "Replace <embed> with <object> if a text alternative is required. "
        "Ensure the title attribute is highly descriptive.",
        "WCAG 1.1.1",
        "H27",
    ))

    return findings


def _audit_video(el: Tag) -> list[Finding]:
    findings = []
    tracks = el.find_all("track")
    caption_tracks = [
        t for t in tracks
        if (t.get("kind") or "").lower() in ("captions", "subtitles")
    ]
    desc_tracks = [
        t for t in tracks
        if (t.get("kind") or "").lower() == "descriptions"
    ]

    # Captions — SC 1.2.2 (Level A, required)
    if not caption_tracks:
        findings.append(make_finding(
            Tier.CRITICAL,
            "No captions track found. Prerecorded video with audio must have "
            "synchronized captions — this is a Level A requirement.",
            'Add a captions track inside the <video> element: '
            '<track kind="captions" src="captions.vtt" srclang="en" '
            'label="English" default>',
            "WCAG 1.2.2",
            "G87",
        ))
    else:
        src = caption_tracks[0].get("src", "inline")
        findings.append(make_finding(
            Tier.PASS,
            f'Captions track found (src="{src}").',
            "",
            "WCAG 1.2.2",
        ))

    # Audio description — SC 1.2.5 (Level AA)
    if not desc_tracks:
        findings.append(make_finding(
            Tier.WARNING,
            "No audio description track found. Visual information not conveyed "
            "in the audio should have an audio description (Level AA requirement).",
            'Add an audio description track: '
            '<track kind="descriptions" src="descriptions.vtt" '
            'srclang="en" label="Audio Description">',
            "WCAG 1.2.5",
            "G78",
        ))
    else:
        findings.append(make_finding(
            Tier.PASS,
            "Audio description track is present.",
            "",
            "WCAG 1.2.5",
        ))

    # Keyboard controls
    if el.get("controls") is None:
        findings.append(make_finding(
            Tier.CRITICAL,
            "Missing controls attribute. Without it, keyboard users cannot "
            "pause, play, stop, or adjust volume.",
            "Add the controls attribute: <video controls ...>",
            "WCAG 2.1.1",
            "G202",
        ))
    else:
        findings.append(make_finding(
            Tier.PASS,
            "controls attribute is present — keyboard users can operate the player.",
            "",
            "WCAG 2.1.1",
        ))

    # Autoplay without mute
    if el.get("autoplay") is not None and el.get("muted") is None:
        findings.append(make_finding(
            Tier.WARNING,
            "autoplay without muted may start audio unexpectedly, "
            "which can disorient screen reader users who rely on audio to navigate.",
            "Add the muted attribute to autoplay video, or remove autoplay. "
            "If autoplay is required, ensure a stop mechanism is available.",
            "WCAG 1.2.2",
            "G171",
        ))

    # Accessible name
    aria_label = (el.get("aria-label") or "").strip()
    aria_labelledby = (el.get("aria-labelledby") or "").strip()
    title = (el.get("title") or "").strip()
    if not aria_label and not aria_labelledby and not title:
        findings.append(make_finding(
            Tier.WARNING,
            "No accessible name on <video>. Screen readers cannot identify "
            "what this video is about.",
            'Add aria-label="[Descriptive title]" to the <video> element.',
            "WCAG 4.1.2",
            "ARIA14",
        ))
    else:
        findings.append(make_finding(
            Tier.PASS,
            "Accessible name is present on <video>.",
            "",
            "WCAG 4.1.2",
        ))

    return findings


def _audit_audio(el: Tag) -> list[Finding]:
    findings = []

    # Keyboard controls
    if el.get("controls") is None:
        findings.append(make_finding(
            Tier.CRITICAL,
            "Missing controls attribute. Keyboard users cannot operate "
            "the audio player.",
            "Add the controls attribute: <audio controls ...>",
            "WCAG 2.1.1",
            "G202",
        ))
    else:
        findings.append(make_finding(
            Tier.PASS,
            "controls attribute is present.",
            "",
            "WCAG 2.1.1",
        ))

    # Transcript — SC 1.2.1 (Level A)
    findings.append(make_finding(
        Tier.MANUAL,
        "Prerecorded audio requires a text transcript (Level A requirement). "
        "Verify that a link to a full transcript is provided near this element.",
        "Add a visible link to a transcript directly after the <audio> element. "
        'Example: <p><a href="transcript.html">Read the audio transcript</a></p>',
        "WCAG 1.2.1",
        "G158",
    ))

    # Autoplay
    if el.get("autoplay") is not None:
        findings.append(make_finding(
            Tier.WARNING,
            "autoplay on <audio> can disrupt screen reader users who depend on "
            "the audio channel to navigate the page.",
            "Remove autoplay, or provide a mechanism to stop audio within "
            "the first 3 seconds (e.g. a clearly labeled stop button).",
            "WCAG 1.2.4",
            "G171",
        ))

    # Accessible name
    aria_label = (el.get("aria-label") or "").strip()
    title = (el.get("title") or "").strip()
    if not aria_label and not title:
        findings.append(make_finding(
            Tier.WARNING,
            "No accessible name on <audio>. Screen readers cannot identify "
            "what this audio contains.",
            'Add aria-label="[Descriptive title]" to the <audio> element.',
            "WCAG 4.1.2",
            "ARIA14",
        ))
    else:
        findings.append(make_finding(
            Tier.PASS,
            "Accessible name is present on <audio>.",
            "",
            "WCAG 4.1.2",
        ))

    return findings


# ── Metadata heuristics ───────────────────────────────────────────────────────

def _apply_metadata_heuristics(
    el: Tag,
    tag_name: str,
    metadata: dict,
    existing_findings: list[Finding],
) -> list[Finding]:
    """
    Apply browser-runtime heuristics from browser_fetcher metadata.
    These checks require live page data that cannot come from static HTML alone.
    """
    findings = []

    is_visible = metadata.get("is_visible", True)
    width = metadata.get("width") or 0
    height = metadata.get("height") or 0
    aria_hidden = str(metadata.get("aria_hidden") or "").lower() == "true"
    tabindex = str(metadata.get("tabindex") or "").strip()
    page_title = metadata.get("page_title", "")
    interactive_count = metadata.get("interactive_count", 0)

    # Tracking pixel / invisible frame
    is_pixel = (width <= 1 and height <= 1) or (not is_visible and width == 0)
    if is_pixel and tag_name == "iframe":
        # Remove the title-missing finding — tracking pixels shouldn't have titles
        # (and shouldn't be shown to AT at all)
        existing_findings[:] = [
            f for f in existing_findings if f.criterion != "WCAG 4.1.2"
        ]
        if not aria_hidden or tabindex != "-1":
            findings.append(make_finding(
                Tier.WARNING,
                "This appears to be a tracking pixel or invisible frame. "
                "It should be completely hidden from assistive technology.",
                'Add aria-hidden="true" and tabindex="-1" to this element.',
                "WCAG 4.1.2",
                "H67",
            ))
        else:
            findings.append(make_finding(
                Tier.PASS,
                "Tracking/invisible frame is correctly hidden from assistive technology.",
                "",
                "WCAG 4.1.2",
            ))
        return findings

    # aria-hidden but still focusable — keyboard trap
    if aria_hidden and tabindex not in ("-1", ""):
        findings.append(make_finding(
            Tier.CRITICAL,
            "This element is aria-hidden but remains in the tab order. "
            "Keyboard users will 'disappear' into hidden content with no way out.",
            'Add tabindex="-1" to remove it from the tab order, since it is '
            "already hidden from screen readers.",
            "WCAG 2.1.1",
            "G202",
        ))

    # Title duplicates the page title
    title_attr = (el.get("title") or "").strip()
    if title_attr and page_title and title_attr.lower() == page_title.lower():
        findings.append(make_finding(
            Tier.WARNING,
            f'The frame title "{title_attr}" is identical to the page title. '
            "This is confusing for screen reader users navigating between frames.",
            f'Make the title more specific, e.g. title="{title_attr} — '
            'Embedded Form" or title="Registration Form".',
            "WCAG 4.1.2",
            "G88",
        ))

    # Complex interactive content
    if interactive_count > 5:
        findings.append(make_finding(
            Tier.MANUAL,
            f"This frame contains {interactive_count} interactive elements. "
            "Verify all internal functionality is keyboard accessible.",
            "Tab through all interactive elements inside the frame and confirm "
            "they can be reached and activated without a mouse.",
            "WCAG 2.1.1",
        ))

    return findings


# ── Fix generators ────────────────────────────────────────────────────────────

def _generate_minimal_fix(el: Tag, tag_name: str, findings: list[Finding]) -> str:
    """
    Apply only safe attribute additions — never alters src, data, type,
    or any functional vendor attribute.
    """
    fixed = copy.copy(el)
    issues = {f.criterion for f in findings if f.tier in (Tier.CRITICAL.value, Tier.WARNING.value)}

    if "WCAG 4.1.2" in issues and not (el.get("title") or "").strip():
        if tag_name in ("iframe", "embed", "object"):
            fixed["title"] = "[Add descriptive title here]"
        else:
            fixed["aria-label"] = "[Add descriptive title here]"

    if "WCAG 2.1.1" in issues and tag_name in ("video", "audio"):
        if el.get("controls") is None:
            fixed["controls"] = True

    return str(fixed)


def _generate_full_fix(el: Tag, tag_name: str, findings: list[Finding]) -> str:
    """
    Full accessible version with wrapper element and all recommended attributes.
    Original vendor attributes (src, data, type, etc.) are preserved unchanged.
    """
    fixed = copy.copy(el)

    # Ensure accessible name
    if not (fixed.get("title") or fixed.get("aria-label") or "").strip():
        if tag_name in ("iframe", "embed", "object"):
            fixed["title"] = "[Add descriptive title here]"
        else:
            fixed["aria-label"] = "[Add descriptive title here]"

    if tag_name == "video":
        if fixed.get("controls") is None:
            fixed["controls"] = True
        # Re-parse to add track children
        inner_soup = BeautifulSoup(str(fixed), "lxml")
        vid = inner_soup.find("video")
        if vid:
            has_captions = any(
                (t.get("kind") or "").lower() in ("captions", "subtitles")
                for t in vid.find_all("track")
            )
            has_desc = any(
                (t.get("kind") or "").lower() == "descriptions"
                for t in vid.find_all("track")
            )
            if not has_captions:
                new_track = inner_soup.new_tag(
                    "track", kind="captions", src="captions.vtt",
                    srclang="en", label="English", default=True,
                )
                vid.append(new_track)
            if not has_desc:
                new_track = inner_soup.new_tag(
                    "track", kind="descriptions",
                    src="descriptions.vtt", srclang="en",
                    label="Audio Description",
                )
                vid.append(new_track)
            label = vid.get("aria-label") or "[Add descriptive title here]"
            return (
                f'<div role="region" aria-label="{label}">\n'
                f'  {str(vid)}\n'
                f'  <p><a href="transcript.html">View full transcript</a></p>\n'
                f'</div>'
            )

    if tag_name == "audio":
        if fixed.get("controls") is None:
            fixed["controls"] = True
        label = fixed.get("aria-label") or "[Add descriptive title here]"
        return (
            f'<div role="region" aria-label="{label}">\n'
            f'  {str(fixed)}\n'
            f'  <p><a href="transcript.html">Read the full transcript</a></p>\n'
            f'</div>'
        )

    if tag_name == "object":
        inner = el.decode_contents().strip()
        if not inner:
            title_val = fixed.get("title") or "Embedded content"
            return (
                f'{str(fixed).replace("</object>", "")}'
                f'<p>{title_val}. '
                f'<a href="#">View alternative version</a></p>'
                f'</object>'
            )

    return str(fixed)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _is_generic_title(title: str) -> bool:
    return (
        not title
        or title.strip().lower() in GENERIC_TITLES
        or len(title.strip()) < 4
    )