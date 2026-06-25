<template>
  <div class="lg-tagin">
    <span v-if="label" class="lg-tagin__label">{{ label }}</span>
    <div class="lg-tagin__chips">
      <span v-for="(tag, idx) in modelValue" :key="`${tag}-${idx}`" class="lg-tagin__chip">
        {{ tag }}
        <button
          type="button"
          class="lg-tagin__remove"
          :aria-label="`移除 ${tag}`"
          @click="removeAt(idx)"
        >
          x
        </button>
      </span>
      <input
        v-model="draft"
        type="text"
        class="lg-tagin__input"
        :placeholder="placeholder ?? '回车添加标签'"
        :disabled="disabled"
        @keydown.enter.prevent="commit"
        @keydown.backspace="onBackspace"
        @blur="commit"
      />
    </div>
    <small v-if="error" class="lg-tagin__error">{{ error }}</small>
    <small v-else-if="hint" class="lg-tagin__hint">{{ hint }}</small>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  modelValue: string[]
  label?: string
  placeholder?: string
  disabled?: boolean
  max?: number
  maxLength?: number
  hint?: string
  error?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [string[]] }>()

const draft = ref('')

function commit(): void {
  const raw = draft.value.trim()
  if (!raw) return
  const next = [...props.modelValue]
  const limitLen = props.maxLength ?? 32
  const max = props.max ?? 16
  const candidate = raw.slice(0, limitLen)
  if (next.find((t) => t.toLowerCase() === candidate.toLowerCase())) {
    draft.value = ''
    return
  }
  if (next.length >= max) {
    draft.value = ''
    return
  }
  next.push(candidate)
  emit('update:modelValue', next)
  draft.value = ''
}

function removeAt(idx: number): void {
  const next = props.modelValue.filter((_, i) => i !== idx)
  emit('update:modelValue', next)
}

function onBackspace(event: KeyboardEvent): void {
  if (draft.value !== '' || props.modelValue.length === 0) return
  event.preventDefault()
  emit('update:modelValue', props.modelValue.slice(0, -1))
}
</script>

<style scoped>
.lg-tagin {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  color: var(--color-text, #d8e1ff);
}
.lg-tagin__label {
  font-size: 0.9rem;
  color: var(--color-text-muted, #8d99c1);
}
.lg-tagin__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 10px;
  padding: 0.45rem 0.55rem;
  min-height: 42px;
}
.lg-tagin__chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: rgba(0, 170, 255, 0.18);
  color: #aee0ff;
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
  font-size: 0.82rem;
}
.lg-tagin__remove {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 0.8rem;
  line-height: 1;
}
.lg-tagin__input {
  flex: 1;
  min-width: 140px;
  background: transparent;
  border: none;
  outline: none;
  color: inherit;
  font-size: 0.92rem;
}
.lg-tagin__error {
  color: #ffadc4;
}
.lg-tagin__hint {
  color: var(--color-text-muted, #8d99c1);
}
</style>
