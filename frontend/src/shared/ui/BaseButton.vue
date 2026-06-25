<template>
  <button
    :type="buttonType"
    :class="['lg-btn', `lg-btn--${buttonVariant}`, { 'lg-btn--block': block, 'is-loading': loading }]"
    :disabled="disabled || loading"
    @click="onClick"
  >
    <span v-if="loading" class="lg-btn__spinner" aria-hidden="true" />
    <span class="lg-btn__label"><slot /></span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type ButtonType = 'button' | 'submit' | 'reset'

const props = withDefaults(
  defineProps<{
    variant?: Variant
    type?: ButtonType
    disabled?: boolean
    loading?: boolean
    block?: boolean
  }>(),
  { variant: 'primary', type: 'button' },
)

const emit = defineEmits<{ click: [MouseEvent] }>()

const buttonVariant = computed<Variant>(() => props.variant)
const buttonType = computed<ButtonType>(() => props.type)

function onClick(event: MouseEvent): void {
  if (props.disabled || props.loading) {
    event.preventDefault()
    return
  }
  emit('click', event)
}
</script>

<style scoped>
.lg-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  border-radius: 999px;
  padding: 0.55rem 1.2rem;
  font-size: 0.95rem;
  font-weight: 500;
  border: 1px solid transparent;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
  min-height: 38px;
}
.lg-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.lg-btn--block {
  width: 100%;
}
.lg-btn--primary {
  background: var(--color-accent, #00aaff);
  color: #04111f;
}
.lg-btn--primary:not(:disabled):hover {
  background: color-mix(in srgb, var(--color-accent, #00aaff) 88%, white);
}
.lg-btn--secondary {
  background: rgba(255, 255, 255, 0.08);
  color: var(--color-text, #d8e1ff);
  border-color: rgba(255, 255, 255, 0.18);
}
.lg-btn--secondary:not(:disabled):hover {
  background: rgba(255, 255, 255, 0.16);
}
.lg-btn--ghost {
  background: transparent;
  color: var(--color-text, #d8e1ff);
  border-color: rgba(255, 255, 255, 0.16);
}
.lg-btn--danger {
  background: rgba(244, 79, 121, 0.18);
  color: #ffb1c5;
  border-color: rgba(244, 79, 121, 0.45);
}
.lg-btn__spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid currentColor;
  border-right-color: transparent;
  animation: lg-btn-spin 0.7s linear infinite;
}
@keyframes lg-btn-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
