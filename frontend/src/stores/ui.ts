/**
 * Cross-feature UI store: search keyword, theme, toasts, modal, sidebar.
 *
 * Setup-store form so it composes naturally with `<script setup>` views.
 * Persisted keys (theme + sidebarCollapsed) are mirrored to localStorage via
 * pinia-plugin-persistedstate; toasts/modal state intentionally stays in
 * memory (transient by definition).
 */
import { computed, reactive, ref } from 'vue'
import { defineStore } from 'pinia'

export type ToastKind = 'info' | 'success' | 'warn' | 'error'

export interface Toast {
  id: number
  message: string
  kind: ToastKind
  /** Auto-dismiss after this many ms. `0` keeps the toast until dismissed. */
  timeoutMs: number
}

export interface ModalState {
  title: string
  body: string
  confirmLabel?: string
  cancelLabel?: string
  onConfirm?: () => void | Promise<void>
}

let nextToastId = 1

export const useUiStore = defineStore(
  'ui',
  () => {
    const keyword = ref('')
    const theme = ref<'dark' | 'light'>('dark')
    const sidebarCollapsed = ref(false)
    const toasts = ref<Toast[]>([])
    const modal = ref<ModalState | null>(null)

    const isDark = computed(() => theme.value === 'dark')

    function setKeyword(value: string): void {
      keyword.value = value
    }

    function toggleTheme(): void {
      theme.value = theme.value === 'dark' ? 'light' : 'dark'
    }

    function pushToast(input: Omit<Toast, 'id'>): number {
      const toast: Toast = { id: nextToastId++, ...input }
      toasts.value = [...toasts.value, toast]
      if (toast.timeoutMs > 0) {
        setTimeout(() => dismissToast(toast.id), toast.timeoutMs)
      }
      return toast.id
    }

    function dismissToast(id: number): void {
      toasts.value = toasts.value.filter((t) => t.id !== id)
    }

    function openModal(state: ModalState): void {
      modal.value = state
    }

    function closeModal(): void {
      modal.value = null
    }

    function toggleSidebar(): void {
      sidebarCollapsed.value = !sidebarCollapsed.value
    }

    function $reset(): void {
      keyword.value = ''
      theme.value = 'dark'
      sidebarCollapsed.value = false
      toasts.value = []
      modal.value = null
    }

    const persistableState = reactive({
      get theme() {
        return theme.value
      },
      set theme(v: 'dark' | 'light') {
        theme.value = v
      },
      get sidebarCollapsed() {
        return sidebarCollapsed.value
      },
      set sidebarCollapsed(v: boolean) {
        sidebarCollapsed.value = v
      },
    })

    return {
      keyword,
      theme,
      isDark,
      sidebarCollapsed,
      toasts,
      modal,
      setKeyword,
      toggleTheme,
      toggleSidebar,
      pushToast,
      dismissToast,
      openModal,
      closeModal,
      $reset,
      // Exposed so plugin-persistedstate can serialize a stable subset
      // without us hand-rolling a serializer.
      persistableState,
    }
  },
  {
    persist: {
      key: 'lg_ui',
      pick: ['theme', 'sidebarCollapsed'],
    },
  },
)
