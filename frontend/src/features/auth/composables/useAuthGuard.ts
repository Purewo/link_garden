/**
 * `useAuthGuard` — composable form of the route-level admin guard.
 *
 * Two responsibilities:
 *
 * 1. Wire the global `auth:invalidated` window event to the auth store.
 *    The shared response interceptor (`shared/api/interceptors.ts`,
 *    owned by B9) dispatches this event on every 401 it sees. Reacting
 *    here keeps the API client free of router or store imports, which
 *    would otherwise create circular dependencies in dev/HMR.
 *
 *    On invalidation:
 *      - clear the auth store (`logout()`)
 *      - if the *current* route's `meta.requiresAdmin === true`,
 *        redirect to `/admin/login?next=<encodeURIComponent(fullPath)>`
 *
 * 2. Expose a small reactive surface (`isAuthenticated`, `isAdmin`,
 *    `user`) plus an imperative `requireAdmin()` helper for components
 *    that gate fragments of the page rather than entire routes.
 *
 * Cross-unit contract:
 *   - The Vue Router instance is provided by B9's `src/router/index.ts`
 *     and accessed via `useRouter()` / `useRoute()` from `vue-router`.
 *   - The window event name (`'auth:invalidated'`) is the contract with
 *     the API interceptor; do not rename without coordinating with B9.
 */
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../store'

/** Window event name shared with `shared/api/interceptors.ts` (B9). */
export const AUTH_INVALIDATED_EVENT = 'auth:invalidated'

/**
 * Build the login URL with a `?next=` redirect target. Keeps URL building
 * out of the call sites so the format is consistent.
 */
export function loginUrlWithNext(fullPath: string): string {
  return `/admin/login?next=${encodeURIComponent(fullPath)}`
}

/**
 * Composable. Call once near the root of any admin-gated component (or
 * once in `App.vue` for app-wide wiring). Multiple invocations are safe
 * — each one registers its own listener and removes it on unmount.
 */
export function useAuthGuard() {
  const auth = useAuthStore()
  const route = useRoute()
  const router = useRouter()

  const isAuthenticated = computed(() => auth.isAuthenticated)
  const isAdmin = computed(() => auth.isAdmin)
  const user = computed(() => auth.user)

  /**
   * Imperative guard for component fragments. Returns `true` when the
   * current user is an admin; otherwise pushes to the login route with
   * a `?next=` redirect target and returns `false`.
   */
  async function requireAdmin(): Promise<boolean> {
    if (auth.isAuthenticated && auth.user === null) {
      // Token persisted across reloads but user object hasn't been
      // hydrated yet. Try once before deciding.
      try {
        await auth.fetchMe()
      } catch {
        // network failure leaves status='error'; treat as gated.
      }
    }
    if (auth.isAdmin) return true
    await router.push(loginUrlWithNext(route.fullPath))
    return false
  }

  /**
   * Listener installed on `window` for the duration of the host
   * component's lifetime. Pulled out as a named function so it can be
   * removed precisely on unmount.
   */
  function onInvalidated(): void {
    auth.logout()
    if (route.meta?.requiresAdmin === true) {
      void router.push(loginUrlWithNext(route.fullPath))
    }
  }

  onMounted(() => {
    if (typeof window !== 'undefined') {
      window.addEventListener(AUTH_INVALIDATED_EVENT, onInvalidated)
    }
  })

  onBeforeUnmount(() => {
    if (typeof window !== 'undefined') {
      window.removeEventListener(AUTH_INVALIDATED_EVENT, onInvalidated)
    }
  })

  return {
    isAuthenticated,
    isAdmin,
    user,
    requireAdmin,
  }
}
