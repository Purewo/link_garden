/**
 * `useCardsStore` — list + detail cache + active filters.
 *
 * Filters are *not* persisted (per phase2-architecture §4.3): a clean
 * homepage matches user expectation better than restoring the last
 * search. Deep-linking is handled by `useFilters()` which mirrors the
 * URL query into this store on route change.
 */
import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import * as cardsApi from './api'
import type { CardListQuery } from './api'
import type {
  CardCreate,
  CardDetail,
  CardListItem,
  CardRead,
  CardUpdate,
} from '../../shared/types/domain'

export interface CardFilters {
  category: string | null
  group: string | null
  tag: string | null
  q: string
  includeArchived: boolean
}

function defaultFilters(): CardFilters {
  return {
    category: null,
    group: null,
    tag: null,
    q: '',
    includeArchived: false,
  }
}

/**
 * Translate the in-memory {@link CardFilters} into the wire shape the
 * backend expects. Empty/null values are dropped so the URL surface
 * stays minimal and the server's defaults apply.
 */
function toQuery(filters: CardFilters): CardListQuery {
  const query: CardListQuery = {}
  if (filters.category) query.category = filters.category as CardListQuery['category']
  if (filters.group) query.group = filters.group as CardListQuery['group']
  if (filters.tag) query.tag = filters.tag
  const trimmed = filters.q.trim()
  if (trimmed) query.q = trimmed
  if (filters.includeArchived) query.include_archived = true
  return query
}

export const useCardsStore = defineStore('cards', () => {
  const list = ref<CardListItem[]>([])
  const byId = ref<Map<string, CardDetail>>(new Map())
  const tags = ref<string[]>([])
  const filters = reactive<CardFilters>(defaultFilters())
  const loading = ref(false)
  const detailLoading = ref(false)
  const error = ref<unknown>(null)

  const filteredCount = computed(() => list.value.length)
  const localCount = computed(
    () => list.value.filter((c) => c.category === 'local').length,
  )

  async function fetchList(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      list.value = await cardsApi.listCards(toQuery(filters))
    } catch (err) {
      error.value = err
      throw err
    } finally {
      loading.value = false
    }
  }

  async function fetchDetail(slug: string): Promise<CardDetail> {
    detailLoading.value = true
    error.value = null
    try {
      const detail = await cardsApi.getCard(slug)
      byId.value.set(detail.id, detail)
      return detail
    } catch (err) {
      error.value = err
      throw err
    } finally {
      detailLoading.value = false
    }
  }

  async function create(payload: CardCreate): Promise<CardDetail> {
    const created = await cardsApi.publish(payload)
    // Optimistic insert at the head; new cards sort first by created_at.
    const summary = toListItem(created)
    list.value = [summary, ...list.value.filter((c) => c.id !== created.id)]
    byId.value.set(created.id, created)
    return created
  }

  async function update(id: string, payload: CardUpdate): Promise<CardDetail> {
    const updated = await cardsApi.update(id, payload)
    const next = toListItem(updated)
    list.value = list.value.map((c) => (c.id === updated.id ? next : c))
    byId.value.set(updated.id, updated)
    return updated
  }

  async function archive(id: string, archived: boolean): Promise<CardRead> {
    const updated = await cardsApi.archive(id, archived)
    if (archived && !filters.includeArchived) {
      list.value = list.value.filter((c) => c.id !== id)
    } else {
      const next = toListItem(updated)
      list.value = list.value.map((c) => (c.id === id ? next : c))
    }
    return updated
  }

  async function remove(id: string): Promise<void> {
    await cardsApi.remove(id)
    list.value = list.value.filter((c) => c.id !== id)
    byId.value.delete(id)
  }

  function setFilter(patch: Partial<CardFilters>): void {
    Object.assign(filters, patch)
  }

  function $reset(): void {
    list.value = []
    byId.value = new Map()
    tags.value = []
    Object.assign(filters, defaultFilters())
    loading.value = false
    detailLoading.value = false
    error.value = null
  }

  return {
    // state
    list,
    byId,
    tags,
    filters,
    loading,
    detailLoading,
    error,
    // derived
    filteredCount,
    localCount,
    // actions
    fetchList,
    fetchDetail,
    create,
    update,
    archive,
    remove,
    setFilter,
    $reset,
  }
})

/**
 * Project a {@link CardDetail} or {@link CardRead} onto the
 * {@link CardListItem} shape for in-place list updates after a write.
 */
function toListItem(card: CardDetail | CardRead): CardListItem {
  return {
    id: card.id,
    slug: card.slug,
    title: card.title,
    category: card.category,
    group: card.group ?? null,
    summary: card.summary,
    tags: card.tags,
    cover: card.cover ?? null,
    archived: card.archived,
    created_at: card.created_at,
  } as CardListItem
}
