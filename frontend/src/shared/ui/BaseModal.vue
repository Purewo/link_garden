<template>
  <Teleport to="body">
    <Transition name="lg-modal-fade">
      <div v-if="open" class="lg-modal" role="dialog" aria-modal="true">
        <div class="lg-modal__backdrop" @click="onBackdrop" />
        <div class="lg-modal__panel" :style="{ maxWidth: `${maxWidth ?? 480}px` }">
          <header v-if="title" class="lg-modal__header">
            <h2>{{ title }}</h2>
            <button type="button" class="lg-modal__close" aria-label="关闭" @click="close">
              ×
            </button>
          </header>
          <div class="lg-modal__body"><slot /></div>
          <footer v-if="$slots.footer" class="lg-modal__footer"><slot name="footer" /></footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
const props = defineProps<{
  open: boolean
  title?: string
  closeOnBackdrop?: boolean
  maxWidth?: number
}>()

const emit = defineEmits<{ 'update:open': [boolean]; close: [] }>()

function close(): void {
  emit('update:open', false)
  emit('close')
}

function onBackdrop(): void {
  if (props.closeOnBackdrop === false) return
  close()
}
</script>

<style scoped>
.lg-modal {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
}
.lg-modal__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(4, 9, 22, 0.72);
  backdrop-filter: blur(6px);
}
.lg-modal__panel {
  position: relative;
  background: var(--color-surface, #111933);
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  padding: 1.4rem;
  width: 100%;
  color: var(--color-text, #d8e1ff);
  box-shadow: 0 22px 48px rgba(0, 0, 0, 0.4);
}
.lg-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.9rem;
}
.lg-modal__header h2 {
  margin: 0;
  font-size: 1.1rem;
}
.lg-modal__close {
  background: none;
  border: none;
  color: inherit;
  font-size: 1.4rem;
  cursor: pointer;
  line-height: 1;
}
.lg-modal__body {
  font-size: 0.95rem;
}
.lg-modal__footer {
  margin-top: 1.2rem;
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
}
.lg-modal-fade-enter-active,
.lg-modal-fade-leave-active {
  transition: opacity 0.18s ease;
}
.lg-modal-fade-enter-from,
.lg-modal-fade-leave-to {
  opacity: 0;
}
</style>
