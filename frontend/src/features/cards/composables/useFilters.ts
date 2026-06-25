/**
 * `useFilters()` binds the URL query string to `useCardsStore.filters`.
 *
 * - URL → store on every route change (initial load + back/forward).
 * - store → URL when the user mutates a filter via `setFilter`, debounced
 *   for `q` so each keystroke doesn't push a history entry.
 * - Re-fetches the list whenever the wire-relevant filter set changes.
 *
 * The store is the source of truth; the URL is a projection. We avoid
 * push-loops by comparing the URL we would write against the current
 * `route.query` before calling `router.replace`.
 */
import { onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { useCardsStore, type CardFilters } from '../store'

const DEBOUNCE_MS = 200

function readFiltersFromQuery(query: Record<string, unknown>): Partial<CardFilters> {
  const next: Partial<CardFilters> = {}
  const category = typeof query.category === 'string' ? query.category : null
  const group = typeof query.group === 'string' ? query.group : null
  const tag = typeof query.tag === 'string' ? query.tag : null
  const q = typeof query.q === 'string' ? query.q : ''
  const includeArchived =
    query.include_archived === '1' ||
    query.include_archived === 'true' ||
    query.include_archived === true
  next.category = category
  next.group = group
  next.tag = tag
  next.q = q
  next.includeArchived = includeArchived
  return next
}

function filtersToQuery(filters: CardFilters): LocationQueryRaw {
  const out: LocationQueryRaw = {}
  if (filters.category) out.category = filters.category
  if (filters.group) out.group = filters.group
  if (filters.tag) out.tag = filters.tag
  const trimmed = filters.q.trim()
  if (trimmed) out.q = trimmed
  if (filters.includeArchived) out.include_archived = '1'
  return out
}

/**
 * Compare two LocationQueryRaw objects for the filter keys we care about.
 * Strict-equality wouldn't catch ordering differences from the router.
 */
function sameQuery(a: LocationQueryRaw, b: LocationQueryRaw): boolean {
  const keys = ['category', 'group', 'tag', 'q', 'include_archived']
  for (const key of keys) {
    if ((a[key] ?? null) !== (b[key] ?? null)) return false
  }
  return true
}

export function useFilters(options: { autoFetch?: boolean } = {}): void {
  const route = useRoute()
  const router = useRouter()
  const store = useCardsStore()
  const autoFetch = options.autoFetch ?? true

  // Apply the initial URL query.
  store.setFilter(readFiltersFromQuery(route.query as Record<string, unknown>))

  // URL → store on every route change. Guard with key check to avoid
  // mutating when navigating to a totally different route.
  const stopRoute = watch(
    () => route.query,
    (q) => {
      store.setFilter(readFiltersFromQuery(q as Record<string, unknown>))
    },
    { flush: 'post' },
  )

  // store → URL, debounced for `q`. The non-search fields write the URL
  // immediately so category/tag chips feel responsive.
  let pending: ReturnType<typeof setTimeout> | null = null
  const stopStore = watch(
    () => ({ ...store.filters }),
    (next) => {
      const queryRaw = filtersToQuery(next as CardFilters)
      const update = () => {
        if (sameQuery(queryRaw, route.query as LocationQueryRaw)) return
        void router.replace({ query: queryRaw })
      }
      if (pending) clearTimeout(pending)
      const isOnlyQ =
        next.category === null && next.group === null && next.tag === null
      pending = setTimeout(update, isOnlyQ ? DEBOUNCE_MS : 0)
    },
    { deep: true },
  )

  // Re-fetch the list whenever the wire-relevant filters change. We pull
  // a stable signature so unrelated UI state (loading/error) doesn't
  // trigger a refetch loop.
  const stopFetch = watch(
    () => [
      store.filters.category,
      store.filters.group,
      store.filters.tag,
      store.filters.q.trim(),
      store.filters.includeArchived,
    ],
    () => {
      if (!autoFetch) return
      void store.fetchList()
    },
    { immediate: autoFetch },
  )

  onBeforeUnmount(() => {
    if (pending) clearTimeout(pending)
    stopRoute()
    stopStore()
    stopFetch()
  })
}
