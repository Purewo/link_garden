/**
 * Domain types — thin re-exports over the generated OpenAPI schema so feature
 * modules can `import type { CardDetail } from '@/shared/types/domain'`
 * without referencing the codegen path everywhere.
 *
 * Regenerate the underlying schema via `pnpm gen:api`.
 */
import type { components } from '@/shared/api/schema'

type Schemas = components['schemas']

export type CardListItem = Schemas['CardListItem']
export type CardRead = Schemas['CardRead']
export type CardDetail = Schemas['CardDetail']
export type CardCreate = Schemas['CardCreate']
export type CardUpdate = Schemas['CardUpdate']
export type CardArchive = Schemas['CardArchive']
export type UserRead = Schemas['UserRead']
export type TokenResponse = Schemas['TokenResponse']
export type LoginRequest = Schemas['LoginRequest']
export type CoverUploadResponse = Schemas['CoverUploadResponse']
export type ErrorEnvelope = Schemas['ErrorEnvelope']
export type OkResponse = Schemas['OkResponse']

/** Storage category — how the card body is hosted. */
export type CardCategory = 'external' | 'local'

/** Content group — surfaced in admin filters / hero columns. */
export type CardGroup = '技术类' | '随笔类' | '生活类'

/** Stable machine error codes the server may emit (kept in sync with backend). */
export type ErrorCode =
  | 'validation_failed'
  | 'missing_url'
  | 'missing_body'
  | 'invalid_category'
  | 'invalid_payload'
  | 'card_not_found'
  | 'slug_conflict'
  | 'tag_too_long'
  | 'invalid_credentials'
  | 'unauthenticated'
  | 'forbidden'
  | 'invalid_image'
  | 'cover_too_large'
  | 'cover_bad_type'
  | 'cover_dim_invalid'
  | 'internal_error'
  | (string & {})
