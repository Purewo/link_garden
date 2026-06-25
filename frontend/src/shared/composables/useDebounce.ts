/**
 * useDebounce — debounce a ref's value. Defaults to 200ms which matches the
 * search input behavior pinned in the architecture spec.
 */
import { customRef, type Ref } from 'vue'

export function useDebounce<T>(initial: T, delayMs = 200): Ref<T> {
  let timer: ReturnType<typeof setTimeout> | null = null
  let value = initial
  return customRef<T>((track, trigger) => ({
    get() {
      track()
      return value
    },
    set(newValue: T) {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        value = newValue
        trigger()
      }, delayMs)
    },
  }))
}
