<template>
  <div class="panel-grid">

    <!-- Input column -->
    <section aria-labelledby="docx-input-heading">
      <div class="card">
        <h2 id="docx-input-heading" class="card-title">DOCX Auditor</h2>

        <div class="field">
          <label for="docx-url">DOCX URL or page containing DOCX files</label>
          <input
            id="docx-url"
            v-model="url"
            type="url"
            placeholder="https://university.edu/document.docx"
            autocomplete="url"
          />
        </div>

        <div class="info-note">
          You can enter a direct .docx URL, or a page URL to find and audit all linked DOCX files.
        </div>

        <div class="or-divider">or upload a file</div>

        <div class="field">
          <label for="docx-file">Upload DOCX file</label>
          <input
            id="docx-file"
            ref="fileInput"
            type="file"
            accept=".docx"
            @change="onFileChange"
          />
        </div>

        <div class="form-actions">
          <button
            class="btn btn-primary"
            :disabled="loading || (!url.trim() && !file)"
            @click="runAudit"
          >
            <span v-if="!loading">Audit DOCX</span>
            <span v-else>
              <span class="spinner" role="status">
                <span class="sr-only">Auditing DOCX…</span>
              </span>
            </span>
          </button>
          <button class="btn btn-ghost" @click="clear">Clear</button>
        </div>
      </div>
    </section>

    <!-- Results column -->
    <section aria-labelledby="docx-results-heading" aria-live="polite">
      <h2 id="docx-results-heading" class="sr-only">DOCX audit results</h2>

      <div v-if="!results.length && !loading && !error" class="results-placeholder">
        <div class="placeholder-icon" aria-hidden="true">📝</div>
        <p>DOCX audit results will appear here</p>
      </div>

      <div v-if="loading" class="loading-container" role="status">
        <div class="spinner" aria-hidden="true"></div>
        <p>Auditing document…</p>
      </div>

      <div v-if="error" class="error-panel" role="alert">
        <strong>Audit failed:</strong> {{ error }}
      </div>

      <template v-if="results.length && !loading">
        <div v-if="results.length > 1" class="card" style="margin-bottom: 1rem;">
          <h3 class="card-title">Page scan summary — {{ results.length }} DOCX files found</h3>
          <ScoreSummary :summary="combinedSummary" label="All DOCX files combined" />
        </div>

        <div
          v-for="(result, idx) in results"
          :key="idx"
          class="card"
          :style="idx > 0 ? 'margin-top: 1rem;' : ''"
        >
          <h3 class="card-title">
            {{ results.length > 1 ? `DOCX ${idx + 1}: ` : '' }}{{ result.source_label }}
          </h3>

          <!-- Document stats -->
          <div v-if="result.metadata" class="docx-stats" aria-label="Document statistics">
            <div class="stat-item">
              <span class="stat-num">{{ result.metadata.paragraphs ?? 0 }}</span>
              <span class="stat-label">Paragraphs</span>
            </div>
            <div class="stat-item">
              <span class="stat-num">{{ result.metadata.headings ?? 0 }}</span>
              <span class="stat-label">Headings</span>
            </div>
            <div class="stat-item">
              <span class="stat-num">{{ result.metadata.tables ?? 0 }}</span>
              <span class="stat-label">Tables</span>
            </div>
            <div class="stat-item">
              <span class="stat-num">{{ result.metadata.images_total ?? 0 }}</span>
              <span class="stat-label">Images</span>
            </div>
            <div class="stat-item">
              <span class="stat-num">{{ result.metadata.links ?? 0 }}</span>
              <span class="stat-label">Links</span>
            </div>
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
import { auditDocx } from '../api.js'
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
  if (file.value) url.value = ''
}

async function runAudit() {
  error.value   = ''
  results.value = []
  loading.value = true

  try {
    const data = await auditDocx({ file: file.value, url: url.value || undefined })
    results.value = data.results ?? []
    if (!results.value.length) {
      error.value = 'No DOCX files found or audited.'
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
.docx-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin: 0.75rem 0;
  padding: 0.75rem;
  background: var(--color-surface-2);
  border-radius: var(--radius);
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 64px;
  padding: 0.5rem;
}

.stat-num {
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--color-brand);
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.stat-label {
  font-size: 0.75rem;
  color: var(--color-text-2);
  margin-top: 0.25rem;
}
</style>