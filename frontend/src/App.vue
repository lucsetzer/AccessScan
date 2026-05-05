<template>
  <div class="app-wrapper">
    <!-- Skip navigation link — WCAG 2.4.1 -->
    <a href="#main-content" class="skip-link">Skip to main content</a>

    <!-- Header -->
    <header class="site-header" role="banner">
      <div class="header-inner">
        <div class="brand">
          <div class="brand-icon" aria-hidden="true">A</div>
          <div>
            <div class="brand-name">AccessScan</div>
            <div class="brand-sub">WCAG 2.2 Accessibility Auditor</div>
          </div>
        </div>
      </div>
    </header>

    <!-- Main content -->
    <main id="main-content" class="main-content">

      <!-- Tab navigation — ARIA tablist pattern -->
      <div
        class="tab-nav"
        role="tablist"
        aria-label="Audit tools"
      >
        <button
          v-for="tab in tabs"
          :key="tab.id"
          :id="`tab-${tab.id}`"
          class="tab-btn"
          role="tab"
          :aria-selected="activeTab === tab.id"
          :aria-controls="`panel-${tab.id}`"
          :tabindex="activeTab === tab.id ? 0 : -1"
          @click="switchTab(tab.id)"
          @keydown="onTabKeydown($event, tab.id)"
        >
          {{ tab.label }}
        </button>
      </div>

      <!-- Tab panels -->
      <div
        v-for="tab in tabs"
        :key="tab.id"
        :id="`panel-${tab.id}`"
        role="tabpanel"
        :aria-labelledby="`tab-${tab.id}`"
        v-show="activeTab === tab.id"
        tabindex="0"
      >
        <component :is="tab.component" @save-result="saveResult" />
      </div>

    </main>

    <!-- Export bar — only visible when results are saved -->
    <div
      v-if="savedResults.length"
      class="export-bar"
      role="region"
      aria-label="Export saved results"
    >
      <div class="export-bar-inner">
        <span class="export-bar-count">
          {{ savedResults.length }} result{{ savedResults.length === 1 ? '' : 's' }} saved
        </span>
        <div class="export-btns">
          <button class="btn btn-sm btn-primary" @click="exportAs('csv')">
            Export CSV
          </button>
          <button class="btn btn-sm btn-secondary" @click="exportAs('pdf')">
            Export PDF Report
          </button>
          <button class="btn btn-sm btn-secondary" @click="exportAs('json')">
            Export JSON
          </button>
          <button class="btn btn-sm btn-ghost" @click="savedResults = []">
            Clear saved
          </button>
        </div>
      </div>
    </div>

    <!-- Screen reader live region for async announcements — WCAG 4.1.3 -->
    <div
      class="sr-only"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >{{ announcement }}</div>

  </div>
</template>

<script setup>
import { ref } from 'vue'
import { exportResults } from './api.js'
import EmbedAuditor  from './components/EmbedAuditor.vue'
import PdfAuditor    from './components/PdfAuditor.vue'
import DocxAuditor   from './components/DocxAuditor.vue'
import SitemapScanner from './components/SitemapScanner.vue'

// ── Tabs ──────────────────────────────────────────────────────────────────────
const tabs = [
  { id: 'embed',   label: 'Embed Auditor',   component: EmbedAuditor   },
  { id: 'pdf',     label: 'PDF Auditor',      component: PdfAuditor     },
  { id: 'docx',    label: 'DOCX Auditor',     component: DocxAuditor    },
  { id: 'sitemap', label: 'Sitemap Scanner',  component: SitemapScanner },
]

const activeTab   = ref('embed')
const savedResults = ref([])
const announcement = ref('')

function switchTab(id) {
  activeTab.value = id
}

// Keyboard navigation for tab list — arrow keys, Home, End
function onTabKeydown(event, currentId) {
  const ids = tabs.map(t => t.id)
  const idx = ids.indexOf(currentId)

  let nextIdx = idx
  if (event.key === 'ArrowRight') nextIdx = (idx + 1) % ids.length
  else if (event.key === 'ArrowLeft') nextIdx = (idx - 1 + ids.length) % ids.length
  else if (event.key === 'Home') nextIdx = 0
  else if (event.key === 'End') nextIdx = ids.length - 1
  else return

  event.preventDefault()
  switchTab(ids[nextIdx])
  // Move focus to the newly selected tab
  document.getElementById(`tab-${ids[nextIdx]}`)?.focus()
}

// ── Saved results / export ────────────────────────────────────────────────────
function saveResult(result) {
  savedResults.value.push(result)
  announcement.value = `Result saved. ${savedResults.value.length} total saved.`
}

async function exportAs(format) {
  try {
    await exportResults({ format, results: savedResults.value })
    announcement.value = `${format.toUpperCase()} export downloaded.`
  } catch (err) {
    announcement.value = `Export failed: ${err.message}`
  }
}
</script>