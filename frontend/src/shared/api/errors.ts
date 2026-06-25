/**
 * Frontend-side error type. The API client rethrows every non-2xx response as
 * an AppError so view code can branch on a stable string code instead of HTTP
 * status numbers.
 */
import type { ErrorCode, ErrorEnvelope } from '@/shared/types/domain'

export class AppError extends Error {
  readonly code: ErrorCode
  readonly status: number
  readonly detail: ReadonlyArray<Record<string, unknown>> | null

  constructor(opts: {
    code: ErrorCode
    message: string
    status: number
    detail?: ReadonlyArray<Record<string, unknown>> | null
  }) {
    super(opts.message)
    this.name = 'AppError'
    this.code = opts.code
    this.status = opts.status
    this.detail = opts.detail ?? null
  }
}

/** Type guard so callers can recover the shape without `instanceof` gymnastics. */
export function isAppError(err: unknown): err is AppError {
  return err instanceof AppError
}

/** Normalize whatever we got back from the server into a usable AppError. */
export function mapError(payload: unknown, status: number): AppError {
  if (isErrorEnvelope(payload)) {
    return new AppError({
      code: payload.code,
      message: payload.error,
      status,
      detail: payload.detail ?? null,
    })
  }

  // Network failure or non-JSON 5xx — synthesize a stable code.
  const fallbackCode: ErrorCode = status === 0 ? 'internal_error' : `http_${status}`
  return new AppError({
    code: fallbackCode,
    message:
      typeof payload === 'string' && payload.length > 0
        ? payload
        : `Request failed with status ${status || 'network'}`,
    status,
    detail: null,
  })
}

/**
 * Convenience for per-feature wrappers that already have an openapi-fetch
 * `{ error, response }` pair. Maps either one into an AppError, preferring
 * any pre-attached envelope from the interceptor.
 */
export function mapResponseError(
  envelope: unknown,
  response: Response | null | undefined,
): AppError {
  if (response) {
    const enriched = response as Response & { __appError?: AppError }
    if (enriched.__appError) return enriched.__appError
    return mapError(envelope ?? null, response.status)
  }
  return mapError(envelope ?? null, 0)
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (!value || typeof value !== 'object') return false
  const v = value as Record<string, unknown>
  return v.ok === false && typeof v.error === 'string' && typeof v.code === 'string'
}
