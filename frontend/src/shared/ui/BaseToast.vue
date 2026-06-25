<template>
  <Teleport to="body">
    <div class="lg-toast-stack" aria-live="polite">
      <TransitionGroup name="lg-toast">
        <div
          v-for="t in toasts"
          :key="t.id"
          :class="['lg-toast', `lg-toast--${t.kind}`]"
          role="status"
        >
          <span class="lg-toast__msg">{{ t.message }}</span>
          <button class="lg-toast__close" aria-label="关闭" @click="dismiss(t.id)">×</button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const { toasts } = storeToRefs(ui)

function dismiss(id: number): void {
  ui.dismissToast(id)
}
</script>

<style scoped>
.lg-toast-stack {
  position: fixed;
  top: 1.2rem;
  right: 1.2rem;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  pointer-events: none;
}
.lg-toast {
  pointer-events: auto;
  background: var(--color-surface, #111933);
  color: var(--color-text, #d8e1ff);
  border-radius: 12px;
  padding: 0.7rem 0.9rem;
  min-width: 240px;
  max-width: 340px;
  display: flex;
  align-items: center;
  gap: 0.7rem;
  border-left: 4px solid var(--color-accent, #00aaff);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.3);
  font-size: 0.92rem;
}
.lg-toast--success {
  border-left-color: #4adf9c;
}
.lg-toast--error {
  border-left-color: #ff6285;
}
.lg-toast--warn {
  border-left-color: #ffc36a;
}
.lg-toast__msg {
  flex: 1;
}
.lg-toast__close {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
}
.lg-toast-enter-from,
.lg-toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
.lg-toast-enter-active,
.lg-toast-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}
</style>
