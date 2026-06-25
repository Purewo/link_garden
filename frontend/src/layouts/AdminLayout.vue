<template>
  <div class="lg-admin">
    <aside class="lg-admin__sidebar" :class="{ 'is-collapsed': ui.sidebarCollapsed }">
      <div class="lg-admin__brand">
        <router-link to="/admin" class="lg-admin__brand-link">Admin</router-link>
        <button class="lg-admin__toggle" type="button" @click="ui.toggleSidebar">☰</button>
      </div>
      <nav class="lg-admin__nav">
        <router-link to="/admin">📚 文章管理</router-link>
        <router-link to="/admin/publish">✍️ 编辑 / 新增</router-link>
        <router-link to="/" class="lg-admin__back-link">↩ 回到前台</router-link>
      </nav>
    </aside>
    <div class="lg-admin__panel">
      <header class="lg-admin__topbar">
        <div class="lg-admin__welcome">
          <span v-if="user">你好，{{ user.username }}</span>
          <span v-else>未登录</span>
        </div>
        <div class="lg-admin__topbar-actions">
          <button v-if="user" type="button" class="lg-admin__logout" @click="onLogout">
            退出
          </button>
        </div>
      </header>
      <main class="lg-admin__main">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * AdminLayout — sidebar nav + top bar. Auth integration is wired up by the
 * auth feature; here we read a single optional store keys ("user") so the
 * layout renders even before B10 lands.
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUiStore } from '@/stores/ui'

interface AuthStoreShape {
  user: { username: string; role: string } | null
  logout: () => void | Promise<void>
}

const ui = useUiStore()
const router = useRouter()

// Auth store is owned by B10; we look it up lazily so the layout works in
// isolation. The any-cast is intentional: this is glue between cooperating
// units, not a typed import.
function getAuthStore(): AuthStoreShape | null {
  try {
    const lookup = (globalThis as { __lgAuthStore?: () => AuthStoreShape }).__lgAuthStore
    return lookup ? lookup() : null
  } catch {
    return null
  }
}

const user = computed(() => getAuthStore()?.user ?? null)

async function onLogout(): Promise<void> {
  const store = getAuthStore()
  if (store) {
    await store.logout()
  }
  await router.push('/admin/login')
}
</script>

<style scoped>
.lg-admin {
  display: flex;
  min-height: 100vh;
  background: var(--color-bg, #060a16);
  color: var(--color-text, #d8e1ff);
}
.lg-admin__sidebar {
  width: 220px;
  background: rgba(255, 255, 255, 0.03);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  padding: 1rem 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
  transition: width 0.2s ease;
}
.lg-admin__sidebar.is-collapsed {
  width: 64px;
}
.lg-admin__sidebar.is-collapsed .lg-admin__brand-link,
.lg-admin__sidebar.is-collapsed .lg-admin__nav a {
  display: none;
}
.lg-admin__brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
}
.lg-admin__brand-link {
  font-weight: 600;
  color: var(--color-text, #d8e1ff);
  text-decoration: none;
}
.lg-admin__toggle {
  background: none;
  border: none;
  color: var(--color-text-muted, #8d99c1);
  font-size: 1.1rem;
  cursor: pointer;
}
.lg-admin__nav {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.lg-admin__nav a {
  color: var(--color-text-muted, #8d99c1);
  text-decoration: none;
  padding: 0.45rem 0.6rem;
  border-radius: 8px;
  font-size: 0.92rem;
}
.lg-admin__nav a:hover,
.lg-admin__nav a.router-link-active {
  background: rgba(255, 255, 255, 0.06);
  color: var(--color-text, #d8e1ff);
}
.lg-admin__back-link {
  margin-top: auto;
}
.lg-admin__panel {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.lg-admin__topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.8rem 1.2rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.lg-admin__welcome {
  color: var(--color-text-muted, #8d99c1);
  font-size: 0.92rem;
}
.lg-admin__logout {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.14);
  color: inherit;
  border-radius: 999px;
  padding: 0.35rem 0.9rem;
  cursor: pointer;
  font-size: 0.85rem;
}
.lg-admin__main {
  flex: 1;
  padding: 1.4rem 1.6rem;
}
</style>
