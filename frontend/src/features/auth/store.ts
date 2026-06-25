/**
 * `useAuthStore` — Pinia 3 setup store for admin authentication.
 *
 * State (persisted to `localStorage` under key `lg_auth`):
 *   - token: HS256 JWT string from `/auth/login`
 *   - user:  `UserRead` snapshot for the active session
 *
 * Volatile state (not persisted):
 *   - status: 'idle' | 'loading' | 'authed' | 'error'
 *   - error:  optional `AppError` from the most recent action
 *
 * Cross-unit contract:
 *   - `pinia-plugin-persistedstate` is registered in `src/main.ts` (B9)
 *   - `AppError` is exported from `shared/api/errors` (B9)
 *   - The shared API client (`shared/api/client`, B9) reads `token` via
 *     this store inside its request interceptor — DO NOT import the
 *     client here or a circular import will surface at HMR time.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { login as loginRequest, me as meRequest } from './api'
import { AppError } from '../../shared/api/errors'
import type { UserRead } from '../../shared/types/domain'

export type AuthStatus = 'idle' | 'loading' | 'authed' | 'error'

/**
 * Setup-store flavour. The persistedstate plugin watches the returned
 * refs by key, so anything we want mirrored to localStorage MUST be
 * named in the `paths` array passed via the store's `persist` option.
 */
export const useAuthStore = defineStore(
  'auth',
  () => {
    const token = ref<string | null>(null)
    const user = ref<UserRead | null>(null)
    const status = ref<AuthStatus>('idle')
    const error = ref<AppError | null>(null)

    const isAuthenticated = computed(() => token.value !== null)
    const isAdmin = computed(() => user.value?.role === 'admin')

    /**
     * Reset every ref to its initial value. Pinia 3 setup stores have no
     * built-in `$reset`, so we hand-roll it. Called by `logout()` and by
     * the `auth:invalidated` listener.
     */
    function $reset(): void {
      token.value = null
      user.value = null
      status.value = 'idle'
      error.value = null
    }

    /**
     * POST /auth/login. On success, mirrors `token` and `user` into
     * persisted state and flips status to 'authed'. On failure, the
     * shared interceptor throws an `AppError`; we capture it on the
     * store and rethrow so the calling component can surface the toast.
     */
    async function login(username: string, password: string): Promise<void> {
      status.value = 'loading'
      error.value = null
      try {
        const res = await loginRequest({ username, password })
        token.value = res.access_token
        user.value = res.user
        status.value = 'authed'
      } catch (err) {
        $reset()
        status.value = 'error'
        error.value = err instanceof AppError ? err : AppError.fromUnknown(err)
        throw error.value
      }
    }

    /**
     * Hydrate `user` from `/auth/me` on app boot when a persisted token
     * exists. A 401 here means the token expired or was revoked —
     * `$reset()` clears local state so the route guard can redirect.
     *
     * Returns `true` when the token is still valid, `false` otherwise.
     * Never throws on auth-shaped errors; transport errors do propagate
     * so callers can distinguish "logged out" from "network is down".
     */
    async function fetchMe(): Promise<boolean> {
      if (token.value === null) {
        return false
      }
      status.value = 'loading'
      error.value = null
      try {
        user.value = await meRequest()
        status.value = 'authed'
        return true
      } catch (err) {
        const appErr =
          err instanceof AppError ? err : AppError.fromUnknown(err)
        if (appErr.status === 401) {
          $reset()
          return false
        }
        status.value = 'error'
        error.value = appErr
        throw appErr
      }
    }

    /**
     * Clear local auth state. There is no server-side logout endpoint in
     * v1 — the JWT is stateless and simply expires after 12h. Components
     * usually pair this with `router.push('/admin/login')`.
     */
    function logout(): void {
      $reset()
    }

    return {
      // state
      token,
      user,
      status,
      error,
      // getters
      isAuthenticated,
      isAdmin,
      // actions
      login,
      logout,
      fetchMe,
      $reset,
    }
  },
  {
    // pinia-plugin-persistedstate options. Only the bearer token and
    // the user snapshot persist; ephemeral status/error stay in memory.
    persist: {
      key: 'lg_auth',
      storage: typeof window !== 'undefined' ? window.localStorage : undefined,
      pick: ['token', 'user'],
    },
  },
)

export type AuthStore = ReturnType<typeof useAuthStore>
