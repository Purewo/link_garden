/**
 * Router entrypoint. The single global `beforeEach` chains the per-route
 * guards in order: title, redirect-if-authed, require-admin.
 */
import {
  createRouter,
  createWebHistory,
  type NavigationGuardNext,
  type RouteLocationNormalized,
} from 'vue-router'
import { routes } from './routes'
import { redirectIfAuthed, requireAdmin, setTitle } from './guards'

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, saved) {
    return saved ?? { top: 0, left: 0 }
  },
})

router.beforeEach(
  async (
    to: RouteLocationNormalized,
    from: RouteLocationNormalized,
    next: NavigationGuardNext,
  ) => {
    setTitle(to, from, next)

    const anon = redirectIfAuthed(to, from, next)
    if (anon !== true && anon !== undefined) {
      return next(anon)
    }

    const admin = await requireAdmin(to, from, next)
    if (admin !== true && admin !== undefined) {
      return next(admin)
    }

    return next()
  },
)

export default router
