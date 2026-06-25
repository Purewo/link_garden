/**
 * Typed API client. Wraps `openapi-fetch` with:
 *   - `/api/v1` base URL (the dev server proxies it to FastAPI)
 *   - Bearer token injection via the auth-token getter (set by `useAuthStore`)
 *   - Uniform error mapping: every non-2xx is normalized to AppError downstream
 *
 * The actual request/response normalization (Bearer attach, 401 broadcast,
 * envelope -> AppError) lives in ./interceptors.ts so this module stays a thin
 * factory.
 */
import createClient from 'openapi-fetch'
import type { paths } from './schema'
import { attachInterceptors } from './interceptors'

export interface ClientOptions {
  baseUrl?: string
}

/** Token resolver injected by the auth store at app boot. */
type TokenGetter = () => string | null

let getToken: TokenGetter = () => null

/**
 * Wire up the token getter. Called from `features/auth/store.ts` once the
 * store is constructed, breaking the circular dependency between the API
 * client and Pinia.
 */
export function setAuthTokenGetter(fn: TokenGetter): void {
  getToken = fn
}

export function readAuthToken(): string | null {
  return getToken()
}

export function createApiClient(opts: ClientOptions = {}) {
  const client = createClient<paths>({
    baseUrl: opts.baseUrl ?? '/api/v1',
  })
  attachInterceptors(client)
  return client
}

/**
 * App-wide singleton. Feature modules should import the per-feature `api.ts`
 * wrappers instead of touching this client directly.
 */
export const api = createApiClient()
