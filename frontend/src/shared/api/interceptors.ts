/**
 * openapi-fetch middleware: attaches the Authorization header and converts any
 * non-2xx response into an AppError. On 401 we dispatch a window event so
 * `useAuthStore` can drop the token without this module importing Pinia or
 * the router (which would create a cycle).
 */
import type { Client, Middleware } from 'openapi-fetch'
import { readAuthToken } from './client'
import { mapError, type AppError } from './errors'

/** Custom event name dispatched on every 401 response. */
export const AUTH_INVALIDATED_EVENT = 'auth:invalidated'

export function dispatchAuthInvalidated(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(AUTH_INVALIDATED_EVENT))
}

const middleware: Middleware = {
  onRequest({ request }) {
    const token = readAuthToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  async onResponse({ response }) {
    if (response.ok) return response

    let payload: unknown = null
    try {
      const contentType = response.headers.get('content-type') ?? ''
      if (contentType.includes('application/json')) {
        payload = (await response.clone().json()) as unknown
      } else {
        payload = await response.clone().text()
      }
    } catch {
      payload = null
    }

    if (response.status === 401) dispatchAuthInvalidated()

    const enriched = response as Response & { __appError?: AppError }
    enriched.__appError = mapError(payload, response.status)
    return response
  },
}

export function attachInterceptors<
  Paths extends Record<string, unknown>,
  Media extends `${string}/${string}`,
>(client: Client<Paths, Media>): void {
  client.use(middleware)
}

/**
 * Helper used by per-feature wrappers: if the response carried an
 * `error` envelope, rethrow as an AppError so callers can `try/catch` once.
 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined) return result.data
  const enriched = result.response as Response & { __appError?: AppError }
  if (enriched.__appError) throw enriched.__appError
  throw mapError(result.error ?? null, result.response.status)
}
