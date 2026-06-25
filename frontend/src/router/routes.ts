/**
 * Route table. Per-feature views are imported lazily so the initial bundle is
 * small (md-editor-v3 + highlight.js are wrapped behind admin/detail chunks).
 *
 * Auth-bearing views may not exist yet (B10/B11/B12 land later). The catch-
 * all NotFoundView is used as a stub for those routes so this scaffold boots
 * without runtime errors.
 */
import type { RouteRecordRaw } from 'vue-router'
import NotFoundView from '@/shared/ui/NotFoundView.vue'

const HomeView = () =>
  import('@/features/cards/views/HomeView.vue').catch(() => ({ default: NotFoundView }))
const CardDetailView = () =>
  import('@/features/cards/views/CardDetailView.vue').catch(() => ({ default: NotFoundView }))
const LoginView = () =>
  import('@/features/auth/views/LoginView.vue').catch(() => ({ default: NotFoundView }))
const AdminCardsView = () =>
  import('@/features/cards/views/AdminCardsView.vue').catch(() => ({ default: NotFoundView }))
const AdminPublishView = () =>
  import('@/features/cards/views/AdminPublishView.vue').catch(() => ({ default: NotFoundView }))

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: HomeView,
    meta: {
      title: 'Link Garden — 是个人博客，也是技术收藏展厅',
      layout: 'public',
    },
  },
  {
    path: '/card/:slug',
    name: 'card-detail',
    component: CardDetailView,
    props: true,
    meta: {
      title: 'Article · Link Garden',
      layout: 'public',
    },
  },
  {
    path: '/admin/login',
    name: 'admin-login',
    component: LoginView,
    meta: {
      title: '登录 · Link Garden',
      layout: 'blank',
      anonOnly: true,
    },
  },
  {
    path: '/admin',
    name: 'admin-cards',
    component: AdminCardsView,
    meta: {
      title: '后台 · 文章管理',
      layout: 'admin',
      requiresAdmin: true,
    },
  },
  {
    path: '/admin/publish',
    name: 'admin-publish',
    component: AdminPublishView,
    meta: {
      title: '后台 · 编辑/新增',
      layout: 'admin',
      requiresAdmin: true,
    },
  },
  {
    path: '/admin/publish/:id',
    name: 'admin-edit',
    component: AdminPublishView,
    props: true,
    meta: {
      title: '后台 · 编辑',
      layout: 'admin',
      requiresAdmin: true,
    },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: NotFoundView,
    meta: {
      title: '404 · Link Garden',
      layout: 'blank',
    },
  },
]
