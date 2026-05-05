# AccessScan

**WCAG 2.2 Accessibility Auditor for Web Pages, PDFs, DOCX Files, and Embedded Content**

Built for UNC Charlotte to help departments audit their web content for ADA and Section 508 compliance. AccessScan scans live pages, uploaded documents, and embedded media — and produces plain-English reports that anyone can understand and act on, regardless of their accessibility experience.

---

## What It Does

| Tab | What it scans | How |
|-----|--------------|-----|
| **Embed Auditor** | `<iframe>`, `<video>`, `<audio>`, `<object>`, `<embed>` | Paste HTML snippet or scan a live page URL |
| **PDF Auditor** | PDF documents | Upload a file, paste a direct PDF URL, or paste a page URL to find all linked PDFs |
| **DOCX Auditor** | Word documents | Upload a file, paste a direct DOCX URL, or paste a page URL to find all linked DOCX files |
| **Sitemap Scanner** | Entire websites | Paste a `sitemap.xml` URL — scans every page for HTML, PDF, and DOCX issues with live streaming progress |

### Checks performed

**HTML pages (via axe-core):**
- Images missing alt text (WCAG 1.1.1)
- Form inputs missing labels (WCAG 3.3.2)
- Color contrast failures (WCAG 1.4.3)
- Missing landmark regions (WCAG 1.3.1)
- Heading structure and hierarchy (WCAG 1.3.1 / 2.4.6)
- Vague link text (WCAG 2.4.4)
- Missing page language (WCAG 3.1.1)
- Missing page title (WCAG 2.4.2)
- Skip navigation links (WCAG 2.4.1)
- ARIA validity (WCAG 4.1.2)
- Viewport zoom disabled (WCAG 1.4.4)
- Focus visibility suppressed (WCAG 2.4.7)

**PDF documents:**
- Missing document title (WCAG 2.4.2)
- Missing language declaration (WCAG 3.1.1)
- Untagged PDF / no reading order (PDF/UA-1)
- Heading structure via tag tree (WCAG 1.3.1)
- Images missing alt text in Figure tags (WCAG 1.1.1)
- Tables missing header rows (WCAG 1.3.1)
- Form fields missing labels (WCAG 3.3.2)
- Vague link text (WCAG 2.4.4)
- Missing bookmarks on long documents (WCAG 2.4.1)

**DOCX documents:**
- Missing document language (WCAG 3.1.1)
- Heading hierarchy and missing H1 (WCAG 1.3.1)
- Images missing alt text (WCAG 1.1.1)
- Tables missing designated header rows (WCAG 1.3.1)
- Vague link text (WCAG 2.4.4)
- Fake lists using manual characters (WCAG 1.3.1)
- All-caps text (readability)
- Excessive blank paragraphs

**Embedded content:**
- Missing or generic title on iframes (WCAG 4.1.2)
- Keyboard access blocked (WCAG 2.1.1)
- Video missing captions track (WCAG 1.2.2)
- Video missing audio description (WCAG 1.2.5)
- Audio missing transcript advisory (WCAG 1.2.1)
- Autoplay without mute (WCAG 1.2.2)
- Tracking pixels not hidden from AT (WCAG 4.1.2)

### Export formats
- **CSV** — for spreadsheet tracking and reporting
- **PDF Report** — formatted report to send to departments
- **JSON** — for integration with other tools

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, uvicorn |
| Browser automation | Playwright (Chromium) |
| PDF parsing | PyMuPDF (fitz), pdfplumber |
| DOCX parsing | python-docx, lxml |
| HTML auditing | axe-core 4.9 (via Playwright) |
| Frontend | Vue 3, Vite |
| Export | ReportLab (PDF), csv |

---

## Local Development Setup

### Prerequisites
- Python 3.12
- Node.js 18+
- Git

### 1. Clone the repo

```bash
git clone https://github.com/lucsetzer/AccessScan.git
cd AccessScan
```

### 2. Backend setup

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
```

Start the backend:
```bash
python -m uvicorn main:app --reload --port 8000
```

Verify: `http://localhost:8000/health` should return `{"status":"ok"}`

### 3. Frontend setup

```bash
cd ../frontend
npm install
npm run dev
```

Open: `http://localhost:5173`

The Vite dev server proxies all `/api` calls to the FastAPI backend automatically.

---

## Project Structure

```
accessscan/
├── backend/
│   ├── main.py                  # FastAPI routes
│   ├── requirements.txt
│   ├── .env.example
│   └── core/
│       ├── schema.py            # Shared data models (Finding, AuditResult)
│       ├── browser.py           # Shared Playwright browser manager
│       └── auditors/
│           ├── embed.py         # iframe/video/audio/object/embed auditor
│           ├── pdf.py           # PDF accessibility auditor
│           ├── docx.py          # DOCX accessibility auditor
│           └── page.py          # HTML page auditor (axe-core)
└── frontend/
    ├── index.html
    ├── vite.config.js
    └── src/
        ├── App.vue              # Main shell, tab navigation
        ├── api.js               # All API calls
        ├── style.css            # Design system (UNCC brand colors)
        └── components/
            ├── EmbedAuditor.vue
            ├── PdfAuditor.vue
            ├── DocxAuditor.vue
            ├── SitemapScanner.vue
            ├── FindingsList.vue  # Shared findings display
            └── ScoreSummary.vue  # Shared score bar
```

---

### Environment variables (production)

Copy `.env.example` to `.env` and set:

```
HOST=0.0.0.0
PORT=8000
MAX_SITEMAP_URLS=50
```

For production, serve the Vite build as static files and point your web server at the FastAPI backend.

```bash
# Build frontend
cd frontend && npm run build

# Serve backend (production)
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## Accessibility of This Tool

AccessScan is itself built to meet WCAG 2.2 AA:

- Full keyboard navigation with visible focus indicators
- ARIA tablist pattern with arrow key support
- Severity badges use color + text label + shape (never color alone)
- Screen reader live region announces async scan results
- Skip navigation link
- All form inputs properly labeled
- 4.5:1 minimum contrast throughout
- No information conveyed by color alone
- Touch targets meet minimum 44×44px

---

## Legal Context

This tool is designed to support compliance with:
- **Americans with Disabilities Act (ADA)** — Title II applies to public universities
- **Section 508 of the Rehabilitation Act** — applies to federally funded institutions
- **WCAG 2.2 Level AA** — the current technical standard referenced by both

AccessScan automates a significant portion of accessibility testing but does not replace manual testing, screen reader testing, or user testing with people with disabilities. Results should be treated as a starting point for remediation, not a certification of compliance.

---

## Contributing

This is an internal UNC Charlotte tool. For bugs or feature requests, open an issue or contact the developer.
