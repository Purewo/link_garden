<template>
  <span class="lg-spinner" role="status" :style="{ width: spinnerSize, height: spinnerSize }" aria-label="加载中" />
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ size?: string }>(), { size: '28px' })
const spinnerSize = computed<string>(() => props.size)
</script>

<style scoped>
.lg-spinner {
  display: inline-block;
  border: 3px solid rgba(255, 255, 255, 0.18);
  border-top-color: var(--color-accent, #00aaff);
  border-radius: 50%;
  animation: lg-spinner-spin 0.9s linear infinite;
}
@keyframes lg-spinner-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
