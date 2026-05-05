<template>
  <div>
    <!-- Filter controls -->
    <div v-if="findings.length > 1" class="findings-filter" role="group" aria-label="Filter findings by severity">
      <button
        v-for="tier in availableTiers"
        :key="tier.value"
        class="filter-btn"
        :class="{ active: activeTier === tier.value }"
        :aria-pressed="activeTier === tier.value"
        @click="activeTier = activeTier === tier.value ? 'all' : tier.value"
      >
        <span :class="`badge badge-${tier.value}`">{{ tier.label }}</span>
        <span class="filter-count">{{ tierCount(tier.value) }}</span>
      </button>
      <button
        class="filter-btn"
        :class="{ active: activeTier === 'all' }"
        :aria-pressed="activeTier === 'all'"
        @click="activeTier = 'all'"
      >
        All
        <span class="filter-count">{{ visibleFindings.length }}</span>
      </button>
    </div>

    <!-- Empty state -->
    <div v-if="filteredFindings.length === 0" class="findings-empty">
      <p v-if="activeTier !== 'all'">
        No {{ activeTier }} findings.
        <button class="btn-link" @click="activeTier = 'all'">Show all findings</button>
      </p>
      <p v-else class="all-clear">
        <span aria-hidden="true">✓</span>
        No accessibility issues found for this item.
      </p>
    </div>

    <!-- Findings -->
    <ul v-else class="findings-list" aria-label="Accessibility findings">
      <li
        v-for="(finding, idx) in filteredFindings"
        :key="idx"
        class="finding-item"
        :class="finding.tier"
      >
        <!-- Header row: badge + description -->
        <div class="finding-header">
          <span :class="`badge badge-${finding.tier}`" :aria-label="`${tierLabel(finding.tier)} issue`">
            {{ tierLabel(finding.tier) }}
          </span>
          <strong>{{ finding.description }}</strong>
        </div>

        <!-- Fix hint -->
        <div v-if="finding.fix_hint" class="finding-fix">
          <strong>How to fix</strong>
          {{ finding.fix_hint }}
        </div>

        <!-- Metadata row: criterion, technique, location, WCAG link -->
        <div
          v-if="finding.criterion || finding.location || finding.wcag_url"
          class="finding-meta"
          aria-label="Finding details"
        >
          <span v-if="finding.criterion" class="finding-meta-item">
            {{ finding.criterion }}
            <span v-if="finding.wcag_level">(Level {{ finding.wcag_level }})</span>
          </span>
          <span v-if="finding.technique" class="finding-meta-item">
            Technique: {{ finding.technique }}
          </span>
          <span v-if="finding.location" class="finding-meta-item">
            Location: {{ finding.location }}
          </span>
          <a
            v-if="finding.wcag_url"
            :href="finding.wcag_url"
            target="_blank"
            rel="noopener noreferrer"
            class="wcag-link finding-meta-item"
          >
            WCAG guidance
            <span class="sr-only">(opens in new tab)</span>
          </a>
        </div>
      </li>
    </ul>

    <!-- Pass/fail summary line -->
    <p v-if="showPasses && passingCount > 0" class="passes-note">
      <span aria-hidden="true">✓</span>
      {{ passingCount }} check{{ passingCount === 1 ? '' : 's' }} passed.
      <button
        v-if="!showingPasses"
        class="btn-link"
        @click="showingPasses = true"
      >Show passing checks</button>
      <button
        v-else
        class="btn-link"
        @click="showingPasses = false"
      >Hide passing checks</button>
    </p>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  findings: {
    type: Array,
    required: true,
  },
  showPasses: {
    type: Boolean,
    default: false,
  },
})

const activeTier = ref('all')
const showingPasses = ref(false)

const TIER_LABELS = {
  critical: 'Critical',
  warning:  'Warning',
  manual:   'Manual Review',
  pass:     'Pass',
}

const tierLabel = (tier) => TIER_LABELS[tier] ?? tier

// Findings excluding passes (unless user opts in)
const visibleFindings = computed(() =>
  props.findings.filter(f => f.tier !== 'pass')
)

const passingCount = computed(() =>
  props.findings.filter(f => f.tier === 'pass').length
)

const filteredFindings = computed(() => {
  const base = showingPasses.value ? props.findings : visibleFindings.value
  if (activeTier.value === 'all') return base
  return base.filter(f => f.tier === activeTier.value)
})

const tierCount = (tier) =>
  visibleFindings.value.filter(f => f.tier === tier).length

// Only show filter buttons for tiers that have findings
const availableTiers = computed(() => {
  const tiers = ['critical', 'warning', 'manual']
  return tiers
    .filter(t => tierCount(t) > 0)
    .map(t => ({ value: t, label: TIER_LABELS[t] }))
})
</script>

<style scoped>
.findings-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1rem;
  align-items: center;
}

.filter-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.75rem;
  background: var(--color-surface-2);
  border: 1.5px solid var(--color-border);
  border-radius: 99px;
  font-family: var(--font-sans);
  font-size: 0.825rem;
  font-weight: 500;
  color: var(--color-text-2);
  cursor: pointer;
  transition: all 0.15s;
}

.filter-btn:hover { background: var(--color-border); color: var(--color-text); }
.filter-btn.active {
  background: var(--color-brand-light);
  border-color: var(--color-brand);
  color: var(--color-brand);
}

.filter-count {
  font-variant-numeric: tabular-nums;
  font-weight: 700;
}

.findings-empty {
  padding: 2rem;
  text-align: center;
  color: var(--color-text-2);
  font-size: 0.9rem;
}

.all-clear {
  color: var(--color-pass);
  font-weight: 500;
}

.passes-note {
  margin-top: 1rem;
  font-size: 0.85rem;
  color: var(--color-pass);
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.btn-link {
  background: none;
  border: none;
  color: var(--color-brand);
  font-family: var(--font-sans);
  font-size: inherit;
  text-decoration: underline;
  cursor: pointer;
  padding: 0;
}
.btn-link:hover { color: var(--color-brand-dark); }
</style>