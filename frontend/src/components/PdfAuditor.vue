<template>
  <div class="panel-grid">

    <!-- Input column -->
    <section aria-labelledby="pdf-input-heading">
      <div class="card">
        <h2 id="pdf-input-heading" class="card-title">PDF Auditor</h2>

        <div class="field">
          <label for="pdf-url">PDF URL or page containing PDFs</label>
          <input
            id="pdf-url"
            v-model="url"
            type="url"
            placeholder="https://university.edu/document.pdf"
            autocomplete="url"
          />
        </div>

        <div class="info-note">
          You can enter a direct .pdf URL, or a page URL to find and audit all linked PDFs.
        </div>

        <div class="or-divider">or upload a file</div>

        <div class="field">
          <label for="pdf-file">Upload PDF file</label>
          <input
            id="pdf-file"
            ref="fileInput"
            type="file"
            accept="application/pdf"
            @change="onFileChange"
          />
        </div>

        <div class="form-actions">
          <button
            class="btn btn-primary"
            :disabled="loading || (!url.trim() && !file)"
            @click="runAudit"
          >
            <span v-if="!loading">Audit PDF</span>
            <span v-else>
              <span class="spinner" role="status">
                <span class="sr-only">Auditing PDF…</span>
              </span>
            </span>
          </button>
          <button class="btn btn-ghost" @click="clear">Clear</button>
        </div>
      </div>
    </section>

    <!-- Results column -->
    <section aria-labelledby="pdf-results-heading" aria-live="polite">
      <h2 id="pdf-results-heading" class="sr-only">PDF audit results</h2>

      <div v-if="!results.length && !loading && !error" class="results-placeholder">
        <div class="placeholder-icon" aria-hidden="true">📄</div>
        <p>PDF audit results will appear here</p>
      </div>

      <div v-if="loading" class="loading-container" role="status">
        <div class="spinner" aria-hidden="true"></div>
        <p>Auditing PDF{{ multipleFiles ? 's' : '' }}… this may take a moment.</p>
      </div>

      <div v-if="error" class="error-panel" role="alert">
        <strong>Audit failed:</strong> {{ error }}
      </div>

      <template v-if="results.length && !loading">
        <!-- Summary across all PDFs if multiple -->
        <div v-if="results.length > 1" class="card" style="margin-bottom: 1rem;">
          <h3 class="card-title">Page scan summary — {{ results.length }} PDFs found</h3>
          <ScoreSummary :summary="combinedSummary" label="All PDFs combined" />
        </div>

        <!-- Individual PDF results -->
        <div
          v-for="(result, idx) in results"
          :key="idx"
          class="card"
          :style="idx > 0 ? 'margin-top: 1rem;' : ''"
        >
          <h3 class="card-title">
            {{ results.length > 1 ? `PDF ${idx + 1}: ` : '' }}{{ result.source_label }}
          </h3>

          <!-- Metadata row -->
          <div v-if="result.metadata" class="pdf-meta" aria-label="Document information">
            <span v-if="result.metadata.pages">{{ result.metadata.pages }} page{{ result.metadata.pages === 1 ? '' : 's' }}</span>
            <span v-if="result.metadata.is_tagged !== undefined">
              {{ result.metadata.is_tagged ? '✓ Tagged' : '✗ Not tagged' }}
            </span>
            <span v-if="result.metadata.language">Language: {{ result.metadata.language }}</span>
            <span v-if="result.metadata.image_count">{{ result.metadata.image_count }} image{{ result.metadata.image_count === 1 ? '' : 's' }}</span>
          </div>

          <ScoreSummary :summary="result.summary" style="margin-top: 1rem;" />
          <FindingsList :findings="result.findings" :show-passes="showPasses" />

          <div class="form-actions" style="margin-top: 1rem;">
            <button class="btn btn-sm btn-secondary" @click="$emit('save-result', result)">
              Save to export
            </button>
          </div>
        </div>

        <div style="margin-top: 1rem; text-align: right;">
          <button class="btn btn-sm btn-ghost" @click="showPasses = !showPasses">
            {{ showPasses ? 'Hide passing checks' : 'Show passing checks' }}
          </button>
        </div>
      </template>
    </section>

  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { auditPdf } from '../api.js'
import ScoreSummary from './ScoreSummary.vue'
import FindingsList from './FindingsList.vue'

const emit = defineEmits(['save-result'])

const url       = ref('')
const file      = ref(null)
const fileInput = ref(null)
const loading   = ref(false)
const error     = ref('')
const results   = ref([])
const showPasses = ref(false)

const multipleFiles = computed(() => results.value.length > 1)

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

function onFileChange(event) {
  file.value = event.target.files[0] ?? null
  if (file.value) url.value = '' // clear URL if file selected
}

async function runAudit() {
  error.value   = ''
  results.value = []
  loading.value = true

  try {
    const data = await auditPdf({ file: file.value, url: url.value || undefined })
    results.value = data.results ?? []
    if (!results.value.length) {
      error.value = 'No PDFs found or audited.'
    }
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function clear() {
  url.value     = ''
  file.value    = null
  results.value = []
  error.value   = ''
  if (fileInput.value) fileInput.value.value = ''
}
</script>

<style scoped>
.pdf-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.825rem;
  color: var(--color-text-2);
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--color-border);
  margin-bottom: 0.5rem;
}
</style>