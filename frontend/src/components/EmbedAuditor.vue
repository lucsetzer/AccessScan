<template>
  <div class="panel-grid">

    <!-- Input column -->
    <section aria-labelledby="embed-input-heading">
      <div class="card">
        <h2 id="embed-input-heading" class="card-title">Embed Auditor</h2>

        <!-- Mode toggle -->
        <div class="mode-toggle" role="group" aria-label="Input method">
          <button
            :class="{ active: mode === 'snippet' }"
            :aria-pressed="mode === 'snippet'"
            @click="mode = 'snippet'"
          >HTML Snippet</button>
          <button
            :class="{ active: mode === 'url' }"
            :aria-pressed="mode === 'url'"
            @click="mode = 'url'"
          >Scan URL</button>
        </div>

        <div v-if="mode === 'snippet'" class="field">
          <label for="embed-snippet">HTML snippet</label>
          <textarea
            id="embed-snippet"
            v-model="snippet"
            rows="9"
            placeholder="Paste an iframe, video, audio, object, or embed tag"
            spellcheck="false"
          />
        </div>

        <div v-if="mode === 'url'" class="field">
          <label for="embed-url">Page URL</label>
          <input
            id="embed-url"
            v-model="url"
            type="url"
            placeholder="https://university.edu/page"
            autocomplete="url"
          />
        </div>

        <div class="form-actions">
          <button
            class="btn btn-primary"
            :disabled="loading || (!snippet.trim() && !url.trim())"
            @click="runAudit"
          >
            <span v-if="!loading">{{ mode === 'snippet' ? 'Audit Snippet' : 'Scan Page' }}</span>
            <span v-else>
              <span class="spinner" role="status">
                <span class="sr-only">Running audit…</span>
              </span>
            </span>
          </button>
          <button class="btn btn-ghost" @click="clear">Clear</button>
        </div>
      </div>
    </section>

    <!-- Results column -->
    <section aria-labelledby="embed-results-heading" aria-live="polite">
      <h2 id="embed-results-heading" class="sr-only">Embed audit results</h2>

      <div v-if="!results.length && !loading && !error" class="results-placeholder">
        <div class="placeholder-icon" aria-hidden="true">⬡</div>
        <p>Audit results will appear here</p>
      </div>

      <div v-if="loading" class="loading-container" role="status">
        <div class="spinner" aria-hidden="true"></div>
        <p>Running audit…</p>
      </div>

      <div v-if="error" class="error-panel" role="alert">
        <strong>Audit failed:</strong> {{ error }}
      </div>

      <template v-if="results.length && !loading">
        <!-- Combined score across all elements found -->
        <ScoreSummary :summary="combinedSummary" label="Embed audit" />

        <!-- One card per element found -->
        <div
          v-for="(result, idx) in results"
          :key="idx"
          class="card"
          style="margin-top: 1rem;"
        >
          <h3 class="card-title">
            Element {{ idx + 1 }}:
            <code style="font-family: var(--font-mono); font-size: 0.9em;">
              &lt;{{ result.metadata?.element_type }}&gt;
            </code>
          </h3>

          <FindingsList :findings="result.findings" :show-passes="showPasses" />

          <!-- Fix code -->
          <div v-if="result.metadata?.minimal_fix" style="margin-top: 1rem;">
            <details>
              <summary style="cursor: pointer; font-weight: 500; font-size: 0.875rem; padding: 0.5rem 0;">
                View suggested fix code
              </summary>
              <div style="margin-top: 0.5rem;">
                <p style="font-size: 0.8rem; color: var(--color-text-2); margin-bottom: 0.5rem;">
                  Minimal fix (safe attribute additions only):
                </p>
                <pre class="code-block">{{ result.metadata.minimal_fix }}</pre>
              </div>
            </details>
          </div>

          <div class="form-actions" style="margin-top: 1rem;">
            <button class="btn btn-sm btn-secondary" @click="$emit('save-result', result)">
              Save to export
            </button>
          </div>
        </div>

        <!-- Show/hide passes toggle -->
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
import { auditEmbed } from '../api.js'
import ScoreSummary from './ScoreSummary.vue'
import FindingsList from './FindingsList.vue'

const emit = defineEmits(['save-result'])

const mode    = ref('snippet')
const snippet = ref('')
const url     = ref('')
const loading = ref(false)
const error   = ref('')
const results = ref([])
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

async function runAudit() {
  error.value   = ''
  results.value = []
  loading.value = true

  try {
    const body = mode.value === 'snippet'
      ? { snippet: snippet.value }
      : { url: url.value }

    const data = await auditEmbed(body)
    results.value = data.results ?? []

    if (!results.value.length) {
      error.value = 'No supported embed elements found (iframe, video, audio, object, embed).'
    }
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function clear() {
  snippet.value = ''
  url.value     = ''
  results.value = []
  error.value   = ''
}
</script>