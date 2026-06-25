<template>
  <label class="lg-select">
    <span v-if="label" class="lg-select__label">{{ label }}</span>
    <select
      :id="id"
      :value="modelValue ?? ''"
      :disabled="disabled"
      class="lg-select__control"
      @change="onChange"
    >
      <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
      <option v-for="opt in options" :key="String(opt.value)" :value="String(opt.value)">
        {{ opt.label }}
      </option>
    </select>
  </label>
</template>

<script setup lang="ts">
interface SelectOption {
  label: string
  value: string | number | null
}

defineProps<{
  modelValue?: string | number | null
  options: SelectOption[]
  label?: string
  id?: string
  placeholder?: string
  disabled?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [string] }>()

function onChange(event: Event): void {
  const target = event.target as HTMLSelectElement
  emit('update:modelValue', target.value)
}
</script>

<style scoped>
.lg-select {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  color: var(--color-text, #d8e1ff);
}
.lg-select__label {
  font-size: 0.9rem;
  color: var(--color-text-muted, #8d99c1);
}
.lg-select__control {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.14);
  color: inherit;
  border-radius: 10px;
  padding: 0.5rem 0.7rem;
  font-size: 0.95rem;
}
.lg-select__control:focus {
  outline: none;
  border-color: var(--color-accent, #00aaff);
}
</style>
