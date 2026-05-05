<template>
  <div class="panel-grid">

    <!-- Input column -->
    <section aria-labelledby="sitemap-input-heading">
      <div class="card">
        <h2 id="sitemap-input-heading" class="card-title">Sitemap Scanner</h2>

        <div class="field">
          <label for="sitemap-url">Sitemap URL</label>
          <input
            id="sitemap-url"
            v-model="sitemapUrl"
            type="url"
            placeholder="https://university.edu/sitemap.xml"
            autocomplete="url"
          />
        </div>

        <fieldset class="field">
          <legend style="font-size: 0.875rem; font-weight: 500; margin-bottom: 0.5rem;">
            Scan for
          </legend>
          <div class="checkbox-group">
            <label>
              <input type="checkbox" v-model="scanTypes" value="page" />
              Page HTML
            </label>
            <label>
              <input type="checkbox" v-model="scanTypes" value="pdf" />
              PDFs
            </label>
            <label>
              <input type="checkbox" v-model="scanTypes" value="docx" />
              DOCX files
            </label>
          </div>
        </fieldset>

        <div class="field">
          <label for="max-urls">Maximum pages to scan</label>
          <input
            id="max-urls"
            v-model.number="maxUrls"
            type="number"
            min="1"
            max="100"
            style="width: 100px;"
          />
          <span style="font-size: 0.825rem; color: var(--color-text-2); margin-left: 0.5rem;">
            (max 100)
          </span>
        </div>

        <div class="info-note">
          Large sitemaps can take several minutes. The scan streams results as each page completes.
        </div>

        <div class="form-actions">
          <button
            class="btn btn-primary"
            :disabled="loading || !sitemapUrl.trim() || !scanTypes.length"
            @click="startScan"
          >
            <span v-if="!loading">Scan Sitemap</span>
            <span v-else>
              <span class="spinner" role="status">
                <span class="sr-only">Scanning…</span>
              </span>
            </span>
          </button>
          <button
            v-if="loading"
            class="btn btn-ghost"
            @click="cancelScan"
          >
            Cancel
          </button>
          <button
            v-if="!loading && results.length"
            class="btn btn-ghost"
            @click="clear"
          >
            Clear
          </button>
        </div>
      </div>

      <!-- Progress log -->
      <div
        v-if="logs.length"
        class="card"
        style="margin-top: 1rem;"
        aria-label="Scan progress log"
      >
        <h3 class="card-title">Scan progress</h3>
        <div
          ref="logContainer"
          class="progress-log"
          role="log"
          aria-live="polite"
          aria-label="Scan log"
        >
          <div
            v-for="(log, idx) in logs"
            :key="idx"
            class="log-line"
            :class="log.level"
          >{{ log.message }}</div>
        </div>

        <!-- Progress bar -->
        <div v-if="progress.total > 0" style="margin-top: 0.75rem;">
          <div
            role="progressbar"
            :aria-valuenow="progress.current"
            :aria-valuemin="0"
            :aria-valuemax="progress.total"
            :aria-label="`Scanning page ${progress.current} of ${progress.total}`"
            style="height: 6px; background: var(--color-border); border-radius: 99px; overflow: hidden;"
          >
            <div
              :style="`width: ${(progress.current / progress.total) * 100}%; height: 100%; background: var(--color-brand); transition: width 0.3s;`"
            ></div>
          </div>
          <p style="font-size: 0.8rem; color: var(--color-text-2); margin-top: 0.25rem;">
            {{ progress.current }} / {{ progress.total }} pages scanned
          </p>
        </div>
      </div>
    </section>

    <!-- Results column -->
    <section aria-labelledby="sitemap-results-heading" aria-live="polite">
      <h2 id="sitemap-results-heading" class="sr-only">Sitemap scan results</h2>

      <div v-if="!results.length && !loading && !error" class="results-placeholder">
        <div class="placeholder-icon" aria-hidden="true">🗺️</div>
        <p>Scan results will appear here as each page is processed</p>
      </div>

      <div v-if="error" class="error-panel" role="alert">
        <strong>Scan failed:</strong> {{ error }}
      </div>

      <template v-if="results.length">
        <!-- Overall summary -->
        <div class="card" style="margin-bottom: 1rem;">
          <h3 class="card-title">
            Overall summary
            <span style="font-weight: 400; font-size: 0.875rem; color: var(--color-text-2);">
              — {{ results.length }} page{{ results.length === 1 ? '' : 's' }} scanned
            </span>
          </h3>
          <ScoreSummary :summary="combinedSummary" label="All pages combined" />

          <div class="form-actions" style="margin-top: 1rem;">
            <button class="btn btn-sm btn-secondary" @click="saveAll">
              Save all to export
            </button>
          </div>
        </div>

        <!-- Per-page results -->
        <div
          v-for="(result, idx) in results"
          :key="idx"
          class="card"
          style="margin-top: 0.75rem;"
        >
          <details>
            <summary class="page-summary-row">
              <div class="page-summary-url">
                <span class="page-index">{{ idx + 1 }}</span>
                <span class="page-url">{{ result.source_label }}</span>
              </div>
              <div class="page-summary-counts" aria-label="Issue counts">
                <span
                  v-if="result.summary?.critical > 0"
                  class="badge badge-critical"
                >{{ result.summary.critical }} critical</span>
                <span
                  v-if="result.summary?.warning > 0"
                  class="badge badge-warning"
                >{{ result.summary.warning }} warning</span>
                <span
                  v-if="result.summary?.manual > 0"
                  class="badge badge-manual"
                >{{ result.summary.manual }} manual</span>
                <span
                  v-if="result.summary?.all_clear"
                  class="badge badge-pass"
                >All clear</span>
              </div>
            </summary>

            <div style="padding-top: 1rem;">
              <FindingsList :findings="result.findings ?? []" />

              <div class="form-actions" style="margin-top: 0.75rem;">
                <button class="btn btn-sm btn-secondary" @click="$emit('save-result', result)">
                  Save to export
                </button>
              </div>
            </div>
          </details>
        </div>
      </template>
    </section>

  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { auditSitemap } from '../api.js'
import ScoreSummary from './ScoreSummary.vue'
import FindingsList from './FindingsList.vue'

const emit = defineEmits(['save-result'])

const sitemapUrl  = ref('')
const scanTypes   = ref(['page', 'pdf', 'docx'])
const maxUrls     = ref(20)
const loading     = ref(false)
const error       = ref('')
const results     = ref([])
const logs        = ref([])
const progress    = ref({ current: 0, total: 0 })
const logContainer = ref(null)
let cancelFn      = null

const combinedSummary = computed(() => {
  const s = { critical: 0, warning: 0, manual: 0, passes: 0 }
  for (const r of results.value) {
    s.critical += r.summary?.critical ?? 0
    s.warning  += r.summary?.warning  ?? 0
    s.manual   += r.summary?.manual   ?? 0
    s.passes   += r.summary?.passes   ?? 0
  }
  return s
})

function addLog(message, level = 'info') {
  logs.value.push({ message, level })
  // Auto-scroll log to bottom
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

function startScan() {
  error.value    = ''
  results.value  = []
  logs.value     = []
  progress.value = { current: 0, total: 0 }
  loading.value  = true

  cancelFn = auditSitemap(
    {
      url: sitemapUrl.value,
      scan_types: scanTypes.value,
      max_urls: maxUrls.value,
    },
    {
      onLog(event) {
        addLog(event.message, event.level)
      },
      onProgress(event) {
        progress.value = { current: event.current, total: event.total }
      },
      onResult(event) {
        results.value.push(event.result)
      },
      onComplete(event) {
        loading.value = false
        cancelFn = null
        const s = event.summary
        addLog(
          `Scan complete — ${s.scanned_urls} pages, ${s.critical} critical, ${s.warning} warnings, ${s.manual} manual`,
          'success',
        )
      },
      onError(message) {
        loading.value = false
        error.value   = message
        cancelFn      = null
        addLog(`Error: ${message}`, 'error')
      },
    },
  )
}

function cancelScan() {
  if (cancelFn) {
    cancelFn()
    cancelFn = null
  }
  loading.value = false
  addLog('Scan cancelled.', 'warning')
}

function saveAll() {
  for (const r of results.value) {
    emit('save-result', r)
  }
}

function clear() {
  results.value  = []
  logs.value     = []
  error.value    = ''
  progress.value = { current: 0, total: 0 }
}
</script>

<style scoped>
.page-summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  cursor: pointer;
  list-style: none;
  flex-wrap: wrap;
}
.page-summary-row::-webkit-details-marker { display: none; }

.page-summary-url {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
  min-width: 0;
}

.page-index {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  background: var(--color-surface-2);
  border-radius: 50%;
  font-size: 0.75rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-2);
}

.page-url {
  font-size: 0.825rem;
  color: var(--color-text);
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.page-summary-counts {
  display: flex;
  gap: 0.375rem;
  flex-wrap: wrap;
  flex-shrink: 0;
}
</style>