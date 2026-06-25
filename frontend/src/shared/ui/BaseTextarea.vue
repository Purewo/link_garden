<template>
  <label class="lg-textarea">
    <span v-if="label" class="lg-textarea__label">{{ label }}</span>
    <textarea
      :id="id"
      :rows="rows ?? 4"
      :value="modelValue ?? ''"
      :placeholder="placeholder"
      :disabled="disabled"
      :required="required"
      class="lg-textarea__control"
      @input="onInput"
    />
    <small v-if="error" class="lg-textarea__error">{{ error }}</small>
    <small v-else-if="hint" class="lg-textarea__hint">{{ hint }}</small>
  </label>
</template>

<script setup lang="ts">
defineProps<{
  modelValue?: string | null
  label?: string
  id?: string
  rows?: number
  placeholder?: string
  disabled?: boolean
  required?: boolean
  hint?: string
  error?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [string] }>()

function onInput(event: Event): void {
  const target = event.target as HTMLTextAreaElement
  emit('update:modelValue', target.value)
}
</script>

<style scoped>
.lg-textarea {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.9rem;
  color: var(--color-text, #d8e1ff);
}
.lg-textarea__label {
  font-weight: 500;
  color: var(--color-text-muted, #8d99c1);
}
.lg-textarea__control {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.14);
  color: inherit;
  border-radius: 10px;
  padding: 0.6rem 0.8rem;
  font-size: 0.95rem;
  resize: vertical;
  min-height: 96px;
  font-family: inherit;
}
.lg-textarea__control:focus {
  outline: none;
  border-color: var(--color-accent, #00aaff);
}
.lg-textarea__error {
  color: #ffadc4;
}
.lg-textarea__hint {
  color: var(--color-text-muted, #8d99c1);
}
</style>
