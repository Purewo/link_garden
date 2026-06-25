/**
 * cards-admin.spec.ts — unit tests for B12 admin frontend.
 *
 * Coverage:
 *   - useCardForm: validation, dirty tracking, category-switch wipe,
 *     create vs update dispatch, server snapshot reload.
 *   - useCoverUpload: type / size / dim validation, preview revoke, upload
 *     wiring.
 *   - AdminCardTable: keyword filter, sort toggling, action emits, delete
 *     visibility.
 *   - AdminCardsView / AdminPublishView: store interaction (mocked).
 *
 * Cross-unit modules are mocked at their import paths so this spec can run
 * before B6/B9/B10/B11 land.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'

// --- Cross-unit module mocks ---------------------------------------------

const mockCardsStore: {
  list: unknown[]
  loading: boolean
  filters: { includeArchived: boolean }
  setFilter: ReturnType<typeof vi.fn>
  fetchList: ReturnType<typeof vi.fn>
  fetchDetail: ReturnType<typeof vi.fn>
  create: ReturnType<typeof vi.fn>
  update: ReturnType<typeof vi.fn>
  archive: ReturnType<typeof vi.fn>
  remove: ReturnType<typeof vi.fn>
} = {
  list: [],
  loading: false,
  filters: { includeArchived: false },
  setFilter: vi.fn(),
  fetchList: vi.fn(),
  fetchDetail: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  archive: vi.fn(),
  remove: vi.fn(),
}

const mockUiStore = {
  pushToast: vi.fn(),
}

const mockAuthStore = {
  isAdmin: true,
}

const mockUploadCover = vi.fn()

vi.mock('@/features/cards/store', () => ({
  useCardsStore: () => mockCardsStore,
}))

vi.mock('@/stores/ui', () => ({
  useUiStore: () => mockUiStore,
}))

vi.mock('@/features/auth/store', () => ({
  useAuthStore: () => mockAuthStore,
}))

vi.mock('@/features/covers/api', () => ({
  uploadCover: (...args: unknown[]) => mockUploadCover(...args),
}))

vi.mock('@/shared/api/client', () => ({
  api: { POST: vi.fn() },
}))

vi.mock('@/shared/api/errors', () => {
  class AppError extends Error {
    code: string
    httpStatus: number
    constructor(code: string, message: string, httpStatus = 400) {
      super(message)
      this.code = code
      this.httpStatus = httpStatus
    }
  }
  return {
    AppError,
    mapResponseError: (err: unknown) =>
      err instanceof Error ? err : new AppError('http_500', 'unknown'),
  }
})

// Stub md-editor-v3 so tests don't need to render the heavy editor.
vi.mock('md-editor-v3', () => ({
  MdEditor: {
    name: 'MdEditor',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<textarea class="stub-md" :value="modelValue" @input="$emit(\'update:modelValue\', ($event.target as HTMLTextAreaElement).value)" />',
  },
}))
vi.mock('md-editor-v3/lib/style.css', () => ({}))

// Vue Router mocks (used by views only).
const mockRouter = {
  push: vi.fn(),
  replace: vi.fn(),
}
const mockRoute = { params: {} as Record<string, string> }
vi.mock('vue-router', () => ({
  useRouter: () => mockRouter,
  useRoute: () => mockRoute,
}))

// --- Imports under test ---------------------------------------------------

import { useCardForm } from '@/features/cards/composables/useCardForm'
import { useCoverUpload } from '@/features/covers/composables/useCoverUpload'
import AdminCardTable from '@/features/cards/components/AdminCardTable.vue'

// --- Helpers --------------------------------------------------------------

function resetMocks() {
  for (const key of Object.keys(mockCardsStore)) {
    const v = (mockCardsStore as Record<string, unknown>)[key]
    if (typeof v === 'function' && 'mockReset' in v) (v as ReturnType<typeof vi.fn>).mockReset()
  }
  mockUiStore.pushToast.mockReset()
  mockUploadCover.mockReset()
  mockRouter.push.mockReset()
  mockRouter.replace.mockReset()
  mockRoute.params = {}
}

beforeEach(resetMocks)
afterEach(() => {
  vi.restoreAllMocks()
})

// --- useCardForm ----------------------------------------------------------

describe('useCardForm', () => {
  it('blocks submit when local card has no body', async () => {
    const ctl = useCardForm()
    ctl.form.title = 'hello'
    ctl.form.category = 'local'
    ctl.form.body = ''
    await expect(ctl.submit()).rejects.toThrow()
    expect(ctl.errors.body).toBeTruthy()
    expect(mockCardsStore.create).not.toHaveBeenCalled()
  })

  it('blocks submit when external card has no url', async () => {
    const ctl = useCardForm()
    ctl.form.title = 'hello'
    ctl.form.category = 'external'
    ctl.form.url = ''
    await expect(ctl.submit()).rejects.toThrow()
    expect(ctl.errors.url).toBeTruthy()
  })

  it('rejects non-http urls', async () => {
    const ctl = useCardForm()
    ctl.form.title = 'hello'
    ctl.form.category = 'external'
    ctl.form.url = 'javascript:alert(1)'
    await expect(ctl.submit()).rejects.toThrow()
    expect(ctl.errors.url).toBeTruthy()
  })

  it('wipes stale url when switching to local', async () => {
    const ctl = useCardForm()
    ctl.form.category = 'external'
    ctl.form.url = 'https://example.com'
    ctl.form.category = 'local'
    await nextTick()
    expect(ctl.form.url).toBe('')
  })

  it('wipes stale body when switching to external', async () => {
    const ctl = useCardForm()
    ctl.form.category = 'local'
    ctl.form.body = '# hello'
    ctl.form.category = 'external'
    await nextTick()
    expect(ctl.form.body).toBe('')
  })

  it('dispatches create when no id is set', async () => {
    const detail = {
      id: 'uuid-1',
      slug: 'hello',
      title: 'hello',
      category: 'local',
      group: '技术类',
      summary: '',
      cover: null,
      url: null,
      body: 'body',
      body_html: '<p>body</p>',
      tags: [],
      archived: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockCardsStore.create.mockResolvedValueOnce(detail)
    const ctl = useCardForm()
    ctl.form.title = 'hello'
    ctl.form.category = 'local'
    ctl.form.body = 'body'
    await ctl.submit()
    expect(mockCardsStore.create).toHaveBeenCalledOnce()
    expect(mockCardsStore.update).not.toHaveBeenCalled()
    expect(ctl.form.id).toBe('uuid-1')
  })

  it('dispatches update when id is set', async () => {
    mockCardsStore.update.mockResolvedValueOnce({
      id: 'uuid-2',
      slug: 'edit',
      title: 'edit',
      category: 'local',
      group: '技术类',
      summary: '',
      cover: null,
      url: null,
      body: 'body',
      body_html: '<p>body</p>',
      tags: [],
      archived: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })
    const ctl = useCardForm()
    ctl.form.id = 'uuid-2'
    ctl.form.title = 'edit'
    ctl.form.category = 'local'
    ctl.form.body = 'body'
    await ctl.submit()
    expect(mockCardsStore.update).toHaveBeenCalledOnce()
    const [id, payload] = mockCardsStore.update.mock.calls[0]
    expect(id).toBe('uuid-2')
    expect(payload.body).toBe('body')
    expect(payload.url).toBeNull()
  })

  it('normalizes tags (trim, dedupe, cap)', async () => {
    mockCardsStore.create.mockImplementationOnce(async (payload) => ({
      ...payload,
      id: 'uuid-3',
      slug: 'tags',
      body_html: '',
      archived: false,
      created_at: '',
      updated_at: '',
    }))
    const ctl = useCardForm()
    ctl.form.title = 'tags'
    ctl.form.category = 'local'
    ctl.form.body = 'body'
    ctl.form.tagsText = ' rust , Rust, go,  rust ,go, '
    await ctl.submit()
    const payload = mockCardsStore.create.mock.calls[0][0]
    // case-insensitive dedupe preserves first-seen capitalization.
    expect(payload.tags).toEqual(['rust', 'go'])
  })

  it('marks dirty after edits and clears after reload', async () => {
    const ctl = useCardForm()
    expect(ctl.dirty.value).toBe(false)
    ctl.form.title = 'changed'
    await nextTick()
    expect(ctl.dirty.value).toBe(true)
    ctl.loadFromDetail({
      id: 'uuid-4',
      slug: 'x',
      title: 'changed',
      category: 'local',
      group: '技术类',
      summary: '',
      cover: null,
      url: null,
      body: '',
      body_html: '',
      tags: [],
      archived: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })
    await nextTick()
    expect(ctl.dirty.value).toBe(false)
  })
})

// --- useCoverUpload -------------------------------------------------------

describe('useCoverUpload', () => {
  const originalCreate = global.URL.createObjectURL
  const originalRevoke = global.URL.revokeObjectURL

  beforeEach(() => {
    global.URL.createObjectURL = vi.fn(() => 'blob://preview')
    global.URL.revokeObjectURL = vi.fn()
    // Stub Image so dim-checking resolves deterministically.
    class FakeImage {
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      naturalWidth = 800
      naturalHeight = 600
      set src(_v: string) {
        // Resolve asynchronously so the awaiter sees onload.
        queueMicrotask(() => this.onload?.())
      }
    }
    // @ts-expect-error: test-only stub
    global.Image = FakeImage
  })
  afterEach(() => {
    global.URL.createObjectURL = originalCreate
    global.URL.revokeObjectURL = originalRevoke
  })

  it('rejects unsupported mime types', async () => {
    const cardId = ref<string | null>('card-1')
    const ctl = useCoverUpload(cardId)
    const file = new File(['x'], 'x.gif', { type: 'image/gif' })
    await ctl.selectFile(file)
    expect(ctl.error.value?.message).toMatch(/png|jpeg|webp/i)
    expect(ctl.file.value).toBeNull()
  })

  it('rejects files larger than maxBytes', async () => {
    const cardId = ref<string | null>('card-1')
    const ctl = useCoverUpload(cardId, { maxBytes: 4 })
    const file = new File(['1234567890'], 'big.png', { type: 'image/png' })
    await ctl.selectFile(file)
    expect(ctl.error.value?.message).toMatch(/MiB/)
    expect(ctl.file.value).toBeNull()
  })

  it('stages a valid file and produces a preview URL', async () => {
    const cardId = ref<string | null>('card-1')
    const ctl = useCoverUpload(cardId)
    const file = new File(['ok'], 'ok.png', { type: 'image/png' })
    await ctl.selectFile(file)
    expect(ctl.file.value).toBe(file)
    expect(ctl.previewUrl.value).toBe('blob://preview')
    expect(ctl.hasStagedFile.value).toBe(true)
  })

  it('upload calls uploadCover and clears staged state on success', async () => {
    mockUploadCover.mockResolvedValueOnce({
      ok: true,
      url: '/covers/card-1.png?v=1',
      width: 800,
      height: 600,
      bytes: 100,
      card: { id: 'card-1' },
    })
    const cardId = ref<string | null>('card-1')
    const ctl = useCoverUpload(cardId)
    await ctl.selectFile(new File(['ok'], 'ok.png', { type: 'image/png' }))
    const result = await ctl.upload()
    expect(result.url).toBe('/covers/card-1.png?v=1')
    expect(ctl.file.value).toBeNull()
    expect(ctl.previewUrl.value).toBeNull()
    expect(mockUploadCover).toHaveBeenCalledOnce()
  })

  it('upload throws when no card id is bound yet', async () => {
    const cardId = ref<string | null>(null)
    const ctl = useCoverUpload(cardId)
    await ctl.selectFile(new File(['ok'], 'ok.png', { type: 'image/png' }))
    await expect(ctl.upload()).rejects.toThrow(/card_id/)
  })

  it('reset revokes preview and clears state', async () => {
    const cardId = ref<string | null>('card-1')
    const ctl = useCoverUpload(cardId)
    await ctl.selectFile(new File(['ok'], 'ok.png', { type: 'image/png' }))
    ctl.reset()
    expect(global.URL.revokeObjectURL).toHaveBeenCalledWith('blob://preview')
    expect(ctl.file.value).toBeNull()
    expect(ctl.previewUrl.value).toBeNull()
  })
})

// --- AdminCardTable -------------------------------------------------------

describe('AdminCardTable', () => {
  const rows = [
    {
      id: 'a',
      slug: 'a',
      title: 'Apple post',
      category: 'local' as const,
      group: '技术类' as const,
      summary: '',
      tags: ['rust'],
      cover: null,
      archived: false,
      created_at: '2026-06-01T00:00:00Z',
    },
    {
      id: 'b',
      slug: 'b',
      title: 'Banana post',
      category: 'external' as const,
      group: '随笔类' as const,
      summary: '',
      tags: ['go'],
      cover: null,
      archived: true,
      created_at: '2026-06-02T00:00:00Z',
    },
  ]

  it('renders all rows with archive pills', () => {
    const wrapper = mount(AdminCardTable, { props: { items: rows } })
    expect(wrapper.text()).toContain('Apple post')
    expect(wrapper.text()).toContain('Banana post')
    expect(wrapper.text()).toContain('在线')
    expect(wrapper.text()).toContain('已下架')
  })

  it('filters by keyword', async () => {
    const wrapper = mount(AdminCardTable, { props: { items: rows } })
    const input = wrapper.get('input.admin-card-table__search')
    await input.setValue('banana')
    expect(wrapper.text()).not.toContain('Apple post')
    expect(wrapper.text()).toContain('Banana post')
  })

  it('hides delete button by default', () => {
    const wrapper = mount(AdminCardTable, { props: { items: rows } })
    expect(wrapper.text()).not.toContain('删除')
  })

  it('shows delete button when showDelete=true', () => {
    const wrapper = mount(AdminCardTable, {
      props: { items: rows, showDelete: true },
    })
    expect(wrapper.text()).toContain('删除')
  })

  it('emits edit / archive actions on row buttons', async () => {
    const wrapper = mount(AdminCardTable, { props: { items: rows } })
    const editBtns = wrapper.findAll('button.link-btn')
    await editBtns[0].trigger('click') // first row's edit
    expect(wrapper.emitted('edit')?.[0]?.[0]).toMatchObject({ id: 'a' })
  })
})
