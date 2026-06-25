/**
 * Typed wrappers around the cards endpoints (`/api/v1/cards`).
 *
 * Views never call the raw openapi-fetch client; they go through these
 * wrappers so feature-specific normalisation (default query merging,
 * data unwrapping, error rethrow) lives in one place.
 *
 * Cross-unit contract: `api` is exported by `shared/api/client.ts` (B9),
 * and the domain types are re-exported from the generated
 * `shared/api/schema.d.ts` (B9 codegen).
 */
import { api } from '@/shared/api/client'
import type {
  CardArchive,
  CardCategory,
  CardCreate,
  CardDetail,
  CardGroup,
  CardListItem,
  CardRead,
  CardUpdate,
} from '@/shared/types/domain'

/**
 * Query parameters for `GET /cards`. The backend exposes this as a
 * `CardListQuery` Pydantic model bound to FastAPI `Query(...)`, but
 * openapi-typescript doesn't lift query models into `components.schemas`,
 * so the type is mirrored here. Keep the keys aligned with
 * `app/features/cards/schemas.py`.
 */
export interface CardListQuery {
  category?: CardCategory | null
  group?: CardGroup | null
  tag?: string | null
  q?: string | null
  include_archived?: boolean
}

/**
 * Throw the envelope-mapped {@link AppError} if openapi-fetch returns one.
 * The shared interceptor already throws on non-2xx, but `error` may also
 * surface for transport-level failures handled in the same shape.
 */
function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error) throw result.error
  if (result.data === undefined) {
    throw new Error('Empty response body from cards API')
  }
  return result.data
}

/**
 * GET /cards
 *
 * Public listing. The server sorts by `created_at DESC, id DESC` and
 * defaults `include_archived=false`. Query keys are passed through as-is
 * so deep-linking from `useFilters` survives a refresh.
 */
export async function listCards(query: CardListQuery = {}): Promise<CardListItem[]> {
  const result = await api.GET('/cards', {
    params: { query: query as Record<string, unknown> },
  })
  return unwrap<CardListItem[]>(result as { data?: CardListItem[]; error?: unknown })
}

/**
 * GET /cards/{slug}
 *
 * Public detail lookup. Returns 404 for archived rows when the caller is
 * unauthenticated — the interceptor turns that into an `AppError` with
 * `code === 'card_not_found'`, which the detail view maps to a 404 state.
 */
export async function getCard(slug: string): Promise<CardDetail> {
  const result = await api.GET('/cards/{slug}', {
    params: { path: { slug } },
  })
  return unwrap<CardDetail>(result as { data?: CardDetail; error?: unknown })
}

/**
 * POST /cards (admin)
 *
 * Admin views (B12) call this through the store. Kept in the public
 * api module because the wrappers are typed once per endpoint, not per
 * caller role.
 */
export async function publish(payload: CardCreate): Promise<CardDetail> {
  const result = await api.POST('/cards', { body: payload })
  return unwrap<CardDetail>(result as { data?: CardDetail; error?: unknown })
}

/**
 * PUT /cards/{id} (admin) — partial-update semantics on the server side.
 */
export async function update(id: string, payload: CardUpdate): Promise<CardDetail> {
  const result = await api.PUT('/cards/{id}', {
    params: { path: { id } },
    body: payload,
  })
  return unwrap<CardDetail>(result as { data?: CardDetail; error?: unknown })
}

/**
 * PATCH /cards/{id}/archive (admin) — setter, not toggle.
 */
export async function archive(id: string, archived: boolean): Promise<CardRead> {
  const body: CardArchive = { archived }
  const result = await api.PATCH('/cards/{id}/archive', {
    params: { path: { id } },
    body,
  })
  return unwrap<CardRead>(result as { data?: CardRead; error?: unknown })
}

/**
 * DELETE /cards/{id} (admin) — hard delete; resolves to void on 204.
 */
export async function remove(id: string): Promise<void> {
  const result = (await api.DELETE('/cards/{id}', {
    params: { path: { id } },
  })) as { error?: unknown }
  if (result.error) throw result.error
}
