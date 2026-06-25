/**
 * useToast — thin facade over the shared UI store so feature code does not
 * need to know about Pinia internals to surface a message. AppError values
 * are converted to a friendly toast title using the stable machine code.
 */
import { useUiStore, type ToastKind } from '@/stores/ui'
import { isAppError } from '@/shared/api/errors'

export function useToast() {
  const ui = useUiStore()

  function push(message: string, kind: ToastKind = 'info', timeoutMs = 3500): void {
    ui.pushToast({ message, kind, timeoutMs })
  }

  function fromError(err: unknown, fallback = '操作失败'): void {
    if (isAppError(err)) {
      push(err.message || fallback, 'error')
    } else if (err instanceof Error) {
      push(err.message || fallback, 'error')
    } else {
      push(fallback, 'error')
    }
  }

  return {
    push,
    success: (message: string, timeoutMs?: number) => push(message, 'success', timeoutMs),
    error: (message: string, timeoutMs?: number) => push(message, 'error', timeoutMs),
    info: (message: string, timeoutMs?: number) => push(message, 'info', timeoutMs),
    warn: (message: string, timeoutMs?: number) => push(message, 'warn', timeoutMs),
    fromError,
    dismiss: ui.dismissToast,
  }
}
