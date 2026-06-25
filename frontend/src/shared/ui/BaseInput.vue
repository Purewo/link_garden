<template>
  <label class="lg-input">
    <span v-if="label" class="lg-input__label">{{ label }}</span>
    <input
      :id="id"
      :type="inputType"
      :value="modelValue ?? ''"
      :placeholder="placeholder"
      :disabled="disabled"
      :required="required"
      :autocomplete="autocomplete"
      :maxlength="maxlength"
      class="lg-input__control"
      @input="onInput"
    />
    <small v-if="error" class="lg-input__error">{{ error }}</small>
    <small v-else-if="hint" class="lg-input__hint">{{ hint }}</small>
  </label>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue?: string | number | null
    label?: string
    placeholder?: string
    type?: string
    id?: string
    disabled?: boolean
    required?: boolean
    hint?: string
    error?: string
    autocomplete?: string
    maxlength?: number
  }>(),
  { type: 'text' },
)

const emit = defineEmits<{ 'update:modelValue': [string] }>()

const inputType = computed<string>(() => props.type)

function onInput(event: Event): void {
  const target = event.target as HTMLInputElement
  emit('update:modelValue', target.value)
}
</script>

<style scoped>
.lg-input {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.9rem;
  color: var(--color-text, #d8e1ff);
}
.lg-input__label {
  font-weight: 500;
  letter-spacing: 0.02em;
  color: var(--color-text-muted, #8d99c1);
}
.lg-input__control {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.14);
  color: inherit;
  border-radius: 10px;
  padding: 0.55rem 0.8rem;
  font-size: 0.95rem;
  transition: border-color 0.18s ease, background 0.18s ease;
}
.lg-input__control:focus {
  outline: none;
  border-color: var(--color-accent, #00aaff);
  background: rgba(255, 255, 255, 0.09);
}
.lg-input__control:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.lg-input__error {
  color: #ffadc4;
}
.lg-input__hint {
  color: var(--color-text-muted, #8d99c1);
}
</style>
