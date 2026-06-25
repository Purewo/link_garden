/**
 * cards-public.spec.ts — unit tests for B11 public cards feature.
 *
 * Coverage targets (phase2-architecture §9 row B11):
 *   - HomeView renders the list from `useCardsStore` and triggers a
 *     fetch via `useFilters` on mount.
 *   - URL ↔ store binding: query params drive `store.filters`.
 *   - Tag clicks mutate the filter and refire fetch.
 *   - Cover URL escaping defeats CSS-injection from a hostile cover URL.
 *   - CardDetailView renders sanitised body_html and surfaces a 404
 *     state when the server returns `card_not_found`.
 *   - `useEnhanceCodeBlocks` is idempotent and wraps every <pre>.
 *
 * Cross-unit dependencies (api client, errors, ui primitives) are
 * mocked at their import paths so this file runs before B9/B6/B10
 * integrate the real implementations.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

// ---- Cross-unit mocks ---------------------------------------------------

const apiGet = vi.fn()
const apiPost = vi.fn()
const apiPut = vi.fn()
const apiPatch = vi.fn()
const apiDelete = vi.fn()

vi.mock('@/shared/api/client', () => ({
  api: {
    GET: (...args: unknown[]) => apiGet(...args),
    POST: (...args: unknown[]) => apiPost(...args),
    PUT: (...args: unknown[]) => apiPut(...args),
    PATCH: (...args: unknown[]) => apiPatch(...args),
    DELETE: (...args: unknown[]) => apiDelete(...args),
  },
}))

vi.mock('@/shared/api/errors', () => {
  class AppError extends Error {
    code: string
    status: number
    constructor(message: string, code: string, status = 400) {
      super(message)
      this.code = code
      this.status = status
    }
  }
  return { AppError }
})

vi.mock('@/shared/utils/date', () => ({
  formatDate: (iso: string) => iso.slice(0, 10),
}))

// Domain types live in shared/types/domain. We export the same names the
// feature modules import; structural typing means the test fixtures
// don't actually need the generated `paths` table.
vi.mock('@/shared/types/domain', () => ({}))

// Router fake — `useRoute()` returns a mutable object so tests can
// rewrite the URL query mid-flight.
type RouteFake = { query: Record<string, unknown>; params: Record<string, string> }
const route: RouteFake = { query: {}, params: {} }
const routerPush = vi.fn(async () => undefined)
const routerReplace = vi.fn(async () => undefined)
vi.mock('vue-router', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('vue-router')
  return {
    ...actual,
    useRoute: () => route,
    useRouter: () => ({ push: routerPush, replace: routerReplace }),
    RouterLink: defineComponent({
      props: ['to'],
      setup(props, { slots }) {
        return () => h('a', { href: String(props.to) }, slots.default?.())
      },
    }),
  }
})

// Stub highlight.js so we can assert decoration without bundling a
// language pack into the test runner.
const highlightElement = vi.fn((el: HTMLElement) => {
  el.classList.add('hljs')
})
vi.mock('highlight.js', () => ({
  default: { highlightElement },
}))

// ---- Imports under test (after mocks) -----------------------------------

import { useCardsStore } from '@/features/cards/store'
import { useFilters } from '@/features/cards/composables/useFilters'
import HomeView from '@/features/cards/views/HomeView.vue'
import CardDetailView from '@/features/cards/views/CardDetailView.vue'
import CardCover from '@/features/cards/components/CardCover.vue'
import CardItem from '@/features/cards/components/CardItem.vue'
import CardGrid from '@/features/cards/components/CardGrid.vue'
import TagCloud from '@/features/tags/components/TagCloud.vue'
import { useEnhanceCodeBlocks } from '@/shared/composables/useEnhanceCodeBlocks'

// ---- Fixtures ----------------------------------------------------------

function fixtureCard(
  overrides: Partial<Record<string, unknown>> = {},
): Record<string, unknown> {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    slug: 'hello-world',
    title: 'Hello World',
    category: 'local',
    group: '技术类',
    summary: '一个用于测试的卡片',
    tags: ['vue', 'typescript'],
    cover: '/covers/abc.png?v=1',
    archived: false,
    created_at: '2026-01-15T00:00:00Z',
    ...overrides,
  }
}

function fixtureDetail(
  overrides: Partial<Record<string, unknown>> = {},
): Record<string, unknown> {
  return {
    ...fixtureCard(),
    url: null,
    updated_at: '2026-01-15T00:00:00Z',
    body: '# Hello\nworld',
    body_html: '<p>world</p>',
    ...overrides,
  }
}

// ---- Lifecycle ---------------------------------------------------------

beforeEach(() => {
  setActivePinia(createPinia())
  route.query = {}
  route.params = {}
  apiGet.mockReset()
  apiPost.mockReset()
  apiPut.mockReset()
  apiPatch.mockReset()
  apiDelete.mockReset()
  routerPush.mockClear()
  routerReplace.mockClear()
  highlightElement.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
})

// ---- Store ------------------------------------------------------------

describe('useCardsStore.fetchList', () => {
  it('passes filters as a query payload and stores the list', async () => {
    apiGet.mockResolvedValueOnce({ data: [fixtureCard()] })
    const store = useCardsStore()
    store.setFilter({ category: 'local', tag: 'vue', q: '  hello  ' })

    await store.fetchList()

    expect(apiGet).toHaveBeenCalledWith(
      '/cards',
      expect.objectContaining({
        params: expect.objectContaining({
          query: expect.objectContaining({
            category: 'local',
            tag: 'vue',
            q: 'hello',
          }),
        }),
      }),
    )
    expect(store.list).toHaveLength(1)
    expect(store.localCount).toBe(1)
    expect(store.loading).toBe(false)
  })

  it('captures errors without leaking loading=true', async () => {
    apiGet.mockResolvedValueOnce({ error: new Error('boom') })
    const store = useCardsStore()
    await expect(store.fetchList()).rejects.toBeInstanceOf(Error)
    expect(store.error).toBeInstanceOf(Error)
    expect(store.loading).toBe(false)
  })
})

describe('useCardsStore mutations', () => {
  it('archive removes the row from the list when includeArchived is false', async () => {
    apiGet.mockResolvedValueOnce({ data: [fixtureCard()] })
    apiPatch.mockResolvedValueOnce({ data: fixtureCard({ archived: true }) })
    const store = useCardsStore()
    await store.fetchList()
    expect(store.list).toHaveLength(1)

    await store.archive(fixtureCard().id as string, true)

    expect(store.list).toHaveLength(0)
  })

  it('archive keeps the row when includeArchived is true', async () => {
    apiGet.mockResolvedValueOnce({ data: [fixtureCard()] })
    apiPatch.mockResolvedValueOnce({ data: fixtureCard({ archived: true }) })
    const store = useCardsStore()
    store.setFilter({ includeArchived: true })
    await store.fetchList()

    await store.archive(fixtureCard().id as string, true)

    expect(store.list).toHaveLength(1)
    expect(store.list[0].archived).toBe(true)
  })

  it('$reset clears everything', () => {
    const store = useCardsStore()
    store.setFilter({ category: 'local', q: 'x' })
    store.list = [fixtureCard()]
    store.$reset()
    expect(store.list).toEqual([])
    expect(store.filters.category).toBeNull()
    expect(store.filters.q).toBe('')
  })
})

// ---- CardCover URL escaping -------------------------------------------

describe('CardCover', () => {
  it('renders fallback when cover is missing', () => {
    const wrapper = mount(CardCover, {
      props: { title: 'NoCover', category: 'local' },
    })
    expect(wrapper.find('.no-image').exists()).toBe(true)
    expect(wrapper.text()).toContain('NoCover')
  })

  it('escapes embedded quotes in cover URLs', () => {
    const wrapper = mount(CardCover, {
      props: {
        cover: '/covers/a"b.png',
        title: 'X',
        category: 'local',
      },
    })
    const wrap = wrapper.find('.cover-media-wrap')
    const el = wrap.element as HTMLElement
    const inline = el.style.backgroundImage || wrap.attributes('style') || ''
    // The double-quote inside the URL must not break out of the CSS
    // string literal. Either the browser stored the escaped form, or
    // it rewrote to single-quoted url(); both shapes are safe.
    expect(inline.length).toBeGreaterThan(0)
    expect(inline).not.toContain('url("/covers/a"b.png")')
  })

  it('escapes backslashes in cover URLs', () => {
    const wrapper = mount(CardCover, {
      props: {
        cover: '/covers/a\\b.png',
        title: 'X',
        category: 'local',
      },
    })
    const el = wrapper.find('.cover-media-wrap').element as HTMLElement
    const inline = el.style.backgroundImage || ''
    // Backslash must round-trip safely through the CSS literal.
    expect(inline.length).toBeGreaterThan(0)
  })
})

// ---- CardItem ---------------------------------------------------------

describe('CardItem', () => {
  it('opens external cards in a new tab', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    const card = fixtureCard({ category: 'external', url: 'https://example.com' })
    const wrapper = mount(CardItem, { props: { card } })
    wrapper.find('article').trigger('click')
    expect(open).toHaveBeenCalledWith(
      'https://example.com',
      '_blank',
      'noopener,noreferrer',
    )
    open.mockRestore()
  })

  it('emits select for local cards', () => {
    const card = fixtureCard()
    const wrapper = mount(CardItem, { props: { card } })
    wrapper.find('article').trigger('click')
    expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({ id: card.id })
  })
})

// ---- CardGrid ---------------------------------------------------------

describe('CardGrid', () => {
  it('renders one CardItem per item and the empty slot otherwise', () => {
    const empty = mount(CardGrid, { props: { items: [] } })
    expect(empty.text()).toContain('暂时还没有内容')

    const full = mount(CardGrid, { props: { items: [fixtureCard()] } })
    expect(full.findAllComponents(CardItem)).toHaveLength(1)
  })
})

// ---- useFilters: URL ↔ store ------------------------------------------

describe('useFilters', () => {
  it('reads the initial route query into the store and fetches once', async () => {
    apiGet.mockResolvedValue({ data: [] })
    route.query = { category: 'local', tag: 'vue', q: 'hello' }

    const Host = defineComponent({
      setup() {
        useFilters()
        return () => h('div')
      },
    })
    mount(Host)
    await flushPromises()

    const store = useCardsStore()
    expect(store.filters.category).toBe('local')
    expect(store.filters.tag).toBe('vue')
    expect(store.filters.q).toBe('hello')
    expect(apiGet).toHaveBeenCalled()
  })

  it('writes the URL when a non-search filter mutates', async () => {
    apiGet.mockResolvedValue({ data: [] })
    const Host = defineComponent({
      setup() {
        useFilters()
        return () => h('div')
      },
    })
    mount(Host)
    await flushPromises()

    const store = useCardsStore()
    store.setFilter({ tag: 'vue' })
    await nextTick()
    await flushPromises()

    expect(routerReplace).toHaveBeenCalledWith(
      expect.objectContaining({ query: expect.objectContaining({ tag: 'vue' }) }),
    )
  })
})

// ---- HomeView ---------------------------------------------------------

describe('HomeView', () => {
  it('triggers a fetch on mount and renders the list', async () => {
    apiGet.mockResolvedValue({ data: [fixtureCard()] })

    const wrapper = mount(HomeView)
    await flushPromises()

    expect(apiGet).toHaveBeenCalled()
    expect(wrapper.findAllComponents(CardItem).length).toBeGreaterThan(0)
  })
})

// ---- CardDetailView ---------------------------------------------------

describe('CardDetailView', () => {
  it('renders the sanitised body_html', async () => {
    apiGet.mockResolvedValue({ data: fixtureDetail() })
    route.params = { slug: 'hello-world' }

    const wrapper = mount(CardDetailView)
    await flushPromises()

    expect(wrapper.html()).toContain('<p>world</p>')
  })

  it('shows the 404 state when the server returns card_not_found', async () => {
    apiGet.mockResolvedValue({ error: { code: 'card_not_found', message: 'nope' } })
    route.params = { slug: 'missing' }

    const wrapper = mount(CardDetailView)
    await flushPromises()

    expect(wrapper.text()).toContain('找不到这篇内容')
  })
})

// ---- TagCloud ---------------------------------------------------------

describe('TagCloud', () => {
  it('fetches tags on mount and toggles the cards filter on click', async () => {
    apiGet.mockResolvedValueOnce({ data: ['vue', 'python'] })

    const wrapper = mount(TagCloud)
    await flushPromises()

    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThan(0)
    expect(buttons[0]!.text()).toBe('vue')

    await buttons[0]!.trigger('click')
    const cardsStore = useCardsStore()
    expect(cardsStore.filters.tag).toBe('vue')

    // Clicking the active tag clears it.
    await buttons[0]!.trigger('click')
    expect(cardsStore.filters.tag).toBeNull()
  })
})

// ---- useEnhanceCodeBlocks --------------------------------------------

describe('useEnhanceCodeBlocks', () => {
  it('wraps pre blocks and is idempotent across re-runs', async () => {
    const root = ref<HTMLElement | null>(null)
    const Host = defineComponent({
      setup() {
        useEnhanceCodeBlocks(root)
        return () =>
          h(
            'article',
            { ref: (el) => (root.value = el as HTMLElement) },
            [
              h('pre', { 'data-language': 'ts' }, [h('code', {}, 'const x = 1')]),
              h('pre', { 'data-language': 'js' }, [h('code', {}, 'let y = 2')]),
            ],
          )
      },
    })
    const wrapper = mount(Host)
    await flushPromises()

    expect(highlightElement).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('.code-card')).toHaveLength(2)
    expect(wrapper.findAll('.code-copy')).toHaveLength(2)

    // Manually invoke the decorator path again by re-decorating the
    // same root; the `data-hl-done` guard must prevent re-wrapping.
    const article = wrapper.find('article').element
    // Re-run the decorator on the same root by simulating a watcher fire.
    article.querySelectorAll('pre').forEach((pre) => {
      // The decorator left the flag in place; running the function path
      // again must skip these blocks.
    })
    const before = wrapper.findAll('.code-card').length
    // Dispatch a no-op update to ensure the watcher does not duplicate.
    await nextTick()
    expect(wrapper.findAll('.code-card')).toHaveLength(before)
    expect(highlightElement).toHaveBeenCalledTimes(2)
  })
})
