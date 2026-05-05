<template>
  <div class="score-bar" role="region" :aria-label="ariaLabel">
    <div class="score-item critical">
      <span class="score-num" aria-hidden="true">{{ summary.critical ?? 0 }}</span>
      <span class="score-label">
        <span class="sr-only">{{ summary.critical ?? 0 }}</span>
        Critical
      </span>
    </div>
    <div class="score-item warning">
      <span class="score-num" aria-hidden="true">{{ summary.warning ?? 0 }}</span>
      <span class="score-label">
        <span class="sr-only">{{ summary.warning ?? 0 }}</span>
        Warning
      </span>
    </div>
    <div class="score-item manual">
      <span class="score-num" aria-hidden="true">{{ summary.manual ?? 0 }}</span>
      <span class="score-label">
        <span class="sr-only">{{ summary.manual ?? 0 }}</span>
        Manual Review
      </span>
    </div>
    <div v-if="showPasses" class="score-item pass">
      <span class="score-num" aria-hidden="true">{{ summary.passes ?? 0 }}</span>
      <span class="score-label">
        <span class="sr-only">{{ summary.passes ?? 0 }}</span>
        Passed
      </span>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  summary: {
    type: Object,
    required: true,
  },
  showPasses: {
    type: Boolean,
    default: false,
  },
  label: {
    type: String,
    default: '',
  },
})

const ariaLabel = props.label
  ? `Audit summary: ${props.label}`
  : 'Audit results summary'
</script>