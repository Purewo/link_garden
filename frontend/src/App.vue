<template>
  <component :is="currentLayout">
    <router-view />
  </component>
  <BaseToast />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import PublicLayout from '@/layouts/PublicLayout.vue'
import AdminLayout from '@/layouts/AdminLayout.vue'
import BlankLayout from '@/layouts/BlankLayout.vue'
import BaseToast from '@/shared/ui/BaseToast.vue'
import { AUTH_INVALIDATED_EVENT } from '@/shared/api/interceptors'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const ui = useUiStore()

type LayoutName = 'public' | 'admin' | 'blank'

const layoutMap: Record<LayoutName, typeof PublicLayout> = {
  public: PublicLayout,
  admin: AdminLayout,
  blank: BlankLayout,
}

const currentLayout = computed(() => {
  const name = (route.meta.layout as LayoutName | undefined) ?? 'public'
  return layoutMap[name] ?? PublicLayout
})

// Listen for 401 invalidations dispatched by the API interceptors. The auth
// store (B10) is responsible for clearing its own state on this event; we
// surface a toast here so the user knows what happened.
function onAuthInvalidated(): void {
  ui.pushToast({
    message: '登录已过期，请重新登录。',
    kind: 'warn',
    timeoutMs: 4000,
  })
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    window.addEventListener(AUTH_INVALIDATED_EVENT, onAuthInvalidated)
  }
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener(AUTH_INVALIDATED_EVENT, onAuthInvalidated)
  }
})
</script>
