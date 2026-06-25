/**
 * Typed wrappers around the auth endpoints (`/api/v1/auth/*`).
 *
 * Views and the auth store never call the raw openapi-fetch client; they go
 * through these wrappers so feature-specific normalisation (envelope
 * unwrapping, error rethrow) lives in one place.
 *
 * Cross-unit contract: `api` is exported by `shared/api/client.ts` (B9), and
 * the domain types are re-exported from the generated
 * `shared/api/schema.d.ts` via `shared/types/domain` (B9 codegen).
 */
import { api } from '@/shared/api/client'
import type {
  LoginRequest,
  TokenResponse,
  UserRead,
} from '@/shared/types/domain'

/**
 * Pull `data` off an openapi-fetch result and rethrow on `error`.
 *
 * The shared response interceptor (B9 `shared/api/interceptors.ts`) is
 * expected to throw `AppError` on non-2xx responses, but `error` may still
 * surface for transport-level failures that bypass the interceptor.
 */
function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error) throw result.error
  if (result.data === undefined) {
    throw new Error('Empty response body from auth API')
  }
  return result.data
}

/**
 * POST /auth/login
 *
 * Exchanges credentials for an HS256 JWT and the matching `UserRead`.
 * The server returns `expires_in=43200` (12h) and uses a constant-time
 * compare so missing-user and bad-password share an identical 401 with
 * `code === 'invalid_credentials'`.
 */
export async function login(payload: LoginRequest): Promise<TokenResponse> {
  const result = await api.POST('/auth/login', { body: payload })
  return unwrap<TokenResponse>(
    result as { data?: TokenResponse; error?: unknown },
  )
}

/**
 * GET /auth/me
 *
 * Validates the persisted bearer token on app boot. A 401 here means the
 * token expired or was revoked; callers (the auth store) clear local state
 * in that case. The `Authorization` header is attached by the shared
 * request interceptor — callers do not pass it explicitly.
 */
export async function me(): Promise<UserRead> {
  const result = await api.GET('/auth/me', {})
  return unwrap<UserRead>(result as { data?: UserRead; error?: unknown })
}
