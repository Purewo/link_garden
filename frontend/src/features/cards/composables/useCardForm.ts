/**
 * useCardForm — encapsulates the publish/edit form state for a Card.
 *
 * Public surface (locked by the architecture spec §4.5):
 *   { form, errors, dirty, submit, reset }
 *
 * Behavior summary:
 *   - Tracks all card fields plus a UI-side `tagsText` string for the chip
 *     input. The composable normalizes that into a `tags: string[]`.
 *   - Validates synchronously on submit; field-level errors live in `errors`.
 *   - When `category` switches, the stale field is wiped (`url` ↔ `body`)
 *     so the server-side coupling check never fails for a stale value.
 *   - `submit()` picks create vs update based on whether `id` is set, calls
 *     into the cards store, and re-throws AppErrors for the view to surface.
 */

import { computed, reactive, ref, watch } from 'vue'
import type { Reactive, Ref } from 'vue'
// Cross-unit dependency — useCardsStore lands in B11 (features/cards/store.ts).
// We import via the canonical path; the integrator wires the actual store.
import { useCardsStore } from '@/features/cards/store'
import type {
  CardCreate,
  CardDetail,
  CardGroup,
  CardCategory,
  CardUpdate,
} from '@/shared/types/domain'

export interface CardFormState {
  id: string | null
  title: string
  category: CardCategory
  group: CardGroup | ''
  summary: string
  cover: string
  url: string
  body: string
  slug: string
  tagsText: string
}

export type CardFormErrors = Partial<Record<keyof CardFormState | 'general', string>>

export interface UseCardFormReturn {
  form: Reactive<CardFormState>
  errors: Reactive<CardFormErrors>
  dirty: Ref<boolean>
  submitting: Ref<boolean>
  isEdit: Ref<boolean>
  submit: () => Promise<CardDetail>
  reset: (next?: Partial<CardFormState>) => void
  /** Hydrate the form from a server CardDetail (used by AdminPublishView edit). */
  loadFromDetail: (detail: CardDetail) => void
}

const TAG_MAX_LEN = 32
const TAG_MAX_COUNT = 16

const blankForm = (): CardFormState => ({
  id: null,
  title: '',
  category: 'local',
  group: '技术类',
  summary: '',
  cover: '',
  url: '',
  body: '',
  slug: '',
  tagsText: '',
})

/**
 * Trim, drop empty, case-insensitive dedupe, cap length, cap count.
 * Mirrors the server-side `tag_list_validator`.
 */
function normalizeTags(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const part of raw.split(/[\s,，、]+/)) {
    const trimmed = part.trim()
    if (!trimmed) continue
    const key = trimmed.toLowerCase()
    if (seen.has(key)) continue
    if (trimmed.length > TAG_MAX_LEN) continue
    seen.add(key)
    out.push(trimmed)
    if (out.length >= TAG_MAX_COUNT) break
  }
  return out
}

function isHttpUrl(value: string): boolean {
  try {
    const u = new URL(value)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

export function useCardForm(initial?: Partial<CardFormState>): UseCardFormReturn {
  const cardsStore = useCardsStore()
  const initialSnapshot: CardFormState = { ...blankForm(), ...initial }
  const form = reactive<CardFormState>({ ...initialSnapshot })
  const errors = reactive<CardFormErrors>({})
  const submitting = ref(false)
  const dirty = ref(false)

  const isEdit = computed(() => Boolean(form.id))

  // Wipe the stale field on category switch so the server-side coupling
  // (`external⇒url`, `local⇒body`) check never trips on leftover data.
  watch(
    () => form.category,
    (next, prev) => {
      if (next === prev) return
      if (next === 'external') form.body = ''
      else form.url = ''
    },
  )

  // Track dirtiness against the initial snapshot.
  watch(
    () => ({ ...form }),
    (next) => {
      dirty.value = JSON.stringify(next) !== JSON.stringify(initialSnapshot)
    },
    { deep: true },
  )

  function clearErrors() {
    for (const key of Object.keys(errors)) {
      delete errors[key as keyof CardFormErrors]
    }
  }

  function validate(): boolean {
    clearErrors()
    if (!form.title.trim()) errors.title = '标题不能为空'
    if (form.category !== 'external' && form.category !== 'local') {
      errors.category = '类型必须是 external 或 local'
    }
    if (form.category === 'external') {
      if (!form.url.trim()) errors.url = '外部文章必须填写跳转链接'
      else if (!isHttpUrl(form.url.trim()))
        errors.url = '链接必须以 http:// 或 https:// 开头'
    }
    if (form.category === 'local' && !form.body.trim()) {
      errors.body = '本站文章必须填写正文'
    }
    if (form.cover && form.cover.trim().toLowerCase().startsWith('javascript:')) {
      errors.cover = '封面 URL 协议不允许'
    }
    return Object.keys(errors).length === 0
  }

  function buildCreatePayload(): CardCreate {
    const payload: CardCreate = {
      title: form.title.trim(),
      category: form.category,
      summary: form.summary.trim(),
      tags: normalizeTags(form.tagsText),
    }
    if (form.group) payload.group = form.group as CardGroup
    if (form.cover.trim()) payload.cover = form.cover.trim()
    if (form.slug.trim()) payload.slug = form.slug.trim()
    if (form.category === 'external') payload.url = form.url.trim()
    if (form.category === 'local') payload.body = form.body
    return payload
  }

  /**
   * Build a partial update payload. We deliberately include every field
   * that is currently present in the form rather than only the dirty ones —
   * the server's CardUpdate honors `model_dump(exclude_unset=True)`, but
   * since this is the only entry point and we always send a full snapshot,
   * "what you see is what gets saved". The behaviour matches the spec's
   * fix for the legacy "PUT silently wipes summary/cover" bug because we
   * always send `summary` and `cover` rather than dropping them.
   */
  function buildUpdatePayload(): CardUpdate {
    const payload: CardUpdate = {
      title: form.title.trim(),
      category: form.category,
      summary: form.summary.trim(),
      tags: normalizeTags(form.tagsText),
      cover: form.cover.trim() || null,
    }
    if (form.group) payload.group = form.group as CardGroup
    if (form.slug.trim()) payload.slug = form.slug.trim()
    if (form.category === 'external') {
      payload.url = form.url.trim()
      payload.body = null
    }
    if (form.category === 'local') {
      payload.body = form.body
      payload.url = null
    }
    return payload
  }

  async function submit(): Promise<CardDetail> {
    if (!validate()) {
      throw new Error('表单校验未通过')
    }
    submitting.value = true
    try {
      const detail = isEdit.value
        ? await cardsStore.update(form.id as string, buildUpdatePayload())
        : await cardsStore.create(buildCreatePayload())
      // Reflect the server snapshot back into the form so subsequent edits
      // start from the canonical state (e.g. the auto-suffixed slug).
      loadFromDetail(detail)
      dirty.value = false
      return detail
    } catch (err) {
      errors.general = err instanceof Error ? err.message : '提交失败'
      throw err
    } finally {
      submitting.value = false
    }
  }

  function reset(next: Partial<CardFormState> = {}) {
    Object.assign(form, blankForm(), next)
    Object.assign(initialSnapshot, { ...form })
    clearErrors()
    dirty.value = false
  }

  function loadFromDetail(detail: CardDetail) {
    form.id = detail.id
    form.title = detail.title ?? ''
    form.category = (detail.category ?? 'local') as CardCategory
    form.group = (detail.group ?? '') as CardGroup | ''
    form.summary = detail.summary ?? ''
    form.cover = detail.cover ?? ''
    form.url = detail.url ?? ''
    form.body = detail.body ?? ''
    form.slug = detail.slug ?? ''
    form.tagsText = (detail.tags ?? []).join(', ')
    Object.assign(initialSnapshot, { ...form })
    clearErrors()
    dirty.value = false
  }

  return {
    form,
    errors,
    dirty,
    submitting,
    isEdit,
    submit,
    reset,
    loadFromDetail,
  }
}
