/**
 * useAsync — small wrapper around an async function so views/components share
 * loading + error state without re-implementing try/finally. No vue-query
 * dependency; the only feature missing is server caching, which is fine for a
 * single-admin blog.
 */
import { ref, shallowRef, type Ref, type ShallowRef } from 'vue'
import { isAppError, mapError, type AppError } from '@/shared/api/errors'

export interface UseAsyncResult<T, Args extends unknown[]> {
  data: ShallowRef<T | null>
  error: Ref<AppError | null>
  loading: Ref<boolean>
  run: (...args: Args) => Promise<T | null>
  reset: () => void
}

export function useAsync<T, Args extends unknown[] = []>(
  fn: (...args: Args) => Promise<T>,
): UseAsyncResult<T, Args> {
  const data = shallowRef<T | null>(null)
  const error = ref<AppError | null>(null)
  const loading = ref(false)

  async function run(...args: Args): Promise<T | null> {
    loading.value = true
    error.value = null
    try {
      const result = await fn(...args)
      data.value = result
      return result
    } catch (err) {
      error.value = isAppError(err) ? err : mapError(err, 0)
      return null
    } finally {
      loading.value = false
    }
  }

  function reset(): void {
    data.value = null
    error.value = null
    loading.value = false
  }

  return { data, error, loading, run, reset }
}
