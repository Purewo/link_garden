/**
 * Shared vitest setup. Loads global polyfills + a typed fetch-mock helper
 * keyed off the generated `paths` types so server/SPA contract drift
 * surfaces at the test call site rather than at runtime.
 *
 * MSW is intentionally not pulled in as a dependency yet; per-test mocks
 * still go through `vi.spyOn(globalThis, 'fetch')`. The helper below is
 * the seam where typed handlers will land once MSW is added.
 */
import { afterEach, vi } from 'vitest'
import type { paths } from '@/shared/api/schema'

// Re-export `paths` so tests can locally narrow against route signatures
// without re-importing the generated module by absolute path.
export type ApiPaths = paths

afterEach(() => {
  vi.restoreAllMocks()
})
