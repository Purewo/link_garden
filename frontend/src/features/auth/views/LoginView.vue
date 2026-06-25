<script setup lang="ts">
/**
 * `LoginView` — admin login route (`/admin/login`).
 *
 * Responsibilities:
 *   - Render the `LoginForm` inside the `blank` layout.
 *   - On success, read `?next=` from the URL and `router.replace` to it.
 *     Falls back to `/admin` when `next` is missing, empty, or unsafe.
 *   - Surface server-side errors via `useToast()` (B9) and an inline
 *     fallback so the form still works if toasts aren't wired yet.
 *   - When the user is already authenticated, the `redirectIfAuthed`
 *     route guard (B9) bounces them to `/admin` before this view ever
 *     mounts. We still defensively re-check on mount in case the user
 *     landed here from a stale tab with a freshly persisted token.
 */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LoginForm from '../components/LoginForm.vue'
import { useAuthStore } from '../store'
import { AppError } from '../../../shared/api/errors'
import { useToast } from '../../../shared/composables/useToast'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const toast = useToast()

const inlineError = ref<AppError | null>(null)

/**
 * Compute the redirect target from `?next=`. Constrained to same-origin
 * absolute paths — anything containing a scheme or starting with `//`
 * is dropped to avoid an open-redirect through the login form.
 */
function nextTarget(): string {
  const raw = route.query.next
  const value = Array.isArray(raw) ? raw[0] : raw
  if (typeof value !== 'string' || value === '') return '/admin'
  // reject schemes (http:, javascript:, data:, …) and protocol-relative URLs
  if (/^[a-z][a-z0-9+.-]*:/i.test(value)) return '/admin'
  if (value.startsWith('//')) return '/admin'
  if (!value.startsWith('/')) return '/admin'
  return value
}

async function handleSuccess(): Promise<void> {
  inlineError.value = null
  await router.replace(nextTarget())
}

function handleError(err: AppError | null): void {
  inlineError.value = err
  if (err !== null) {
    toast.error(err.message, { code: err.code })
  }
}

onMounted(() => {
  // Defensive: route guard `redirectIfAuthed` normally handles this.
  if (auth.isAuthenticated && auth.user !== null) {
    void router.replace(nextTarget())
  }
})
</script>

<template>
  <main class="login-view">
    <section class="login-view__card" aria-labelledby="login-heading">
      <header class="login-view__header">
        <h1 id="login-heading" class="login-view__title">登录 Link Garden</h1>
        <p class="login-view__subtitle">仅管理员可登录后台。</p>
      </header>

      <LoginForm
        @success="handleSuccess"
        @update:error="handleError"
      />

      <p
        v-if="inlineError"
        class="login-view__error"
        role="alert"
        :data-code="inlineError.code"
      >
        {{ inlineError.message }}
      </p>
    </section>
  </main>
</template>

<style scoped>
.login-view {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 2rem 1rem;
  background: var(--lg-bg-surface, #f6f6f8);
}

.login-view__card {
  width: 100%;
  max-width: 22rem;
  padding: 2rem 1.75rem;
  border-radius: 12px;
  background: var(--lg-bg-card, #ffffff);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.login-view__header {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.login-view__title {
  margin: 0;
  font-size: 1.375rem;
  font-weight: 600;
  color: var(--lg-text-strong, #222);
}

.login-view__subtitle {
  margin: 0;
  font-size: 0.875rem;
  color: var(--lg-text-muted, #666);
}

.login-view__error {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--lg-color-danger, #c0392b);
}
</style>
