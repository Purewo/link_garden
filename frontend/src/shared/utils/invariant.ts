/**
 * invariant — narrowing helper for asserted branches. Mirrors the TS
 * `asserts` semantics so the compiler treats the call as a refinement.
 */
export function invariant(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(`Invariant failed: ${message}`)
  }
}
