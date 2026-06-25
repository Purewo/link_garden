/**
 * Per-route navigation guards. Each guard is small and composable — the
 * top-level `beforeEach` chains them so behavior stays declarative.
 *
 * `requireAdmin` and `redirectIfAuthed` consult the auth store via a globally
 * stashed accessor (set by `features/auth/store.ts` in B10). When the auth
 * unit hasn't merged yet, the guards behave permissively (auth state assumed
 * empty), letting the scaffold render without B10.
 */
import type { NavigationGuardWithThis, RouteLocationNormalized } from 'vue-router'

interface AuthStoreShape {
  token: string | null
  user: { role: string } | null
  isAuthenticated?: boolean
  isAdmin?: boolean
  fetchMe?: () => Promise<unknown>
}

declare global {
  // eslint-disable-next-line no-var, vars-on-top
  var __lgAuthStore: (() => AuthStoreShape) | undefined
}

function readAuth(): AuthStoreShape | null {
  return globalThis.__lgAuthStore ? globalThis.__lgAuthStore() : null
}

export const setTitle: NavigationGuardWithThis<undefined> = (to) => {
  const title = (to.meta.title as string | undefined) ?? 'Link Garden'
  if (typeof document !== 'undefined') document.title = title
  return true
}

export const requireAdmin: NavigationGuardWithThis<undefined> = async (
  to: RouteLocationNormalized,
) => {
  if (!to.meta.requiresAdmin) return true
  const auth = readAuth()
  if (!auth || !auth.token) {
    return loginRedirect(to.fullPath)
  }
  if (!auth.user && auth.fetchMe) {
    try {
      await auth.fetchMe()
    } catch {
      return loginRedirect(to.fullPath)
    }
  }
  if (!auth.user || auth.user.role !== 'admin') {
    return loginRedirect(to.fullPath)
  }
  return true
}

export const redirectIfAuthed: NavigationGuardWithThis<undefined> = (to) => {
  if (!to.meta.anonOnly) return true
  const auth = readAuth()
  if (auth?.token && auth.user?.role === 'admin') {
    const next = typeof to.query.next === 'string' ? to.query.next : '/admin'
    return next
  }
  return true
}

function loginRedirect(next: string): { path: string; query: Record<string, string> } {
  return { path: '/admin/login', query: { next } }
}
