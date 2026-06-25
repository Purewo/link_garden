/**
 * Typed wrapper around `/api/v1/tags`.
 *
 * Default excludes archived (fixes the legacy bug where archived cards'
 * tags leaked into the public list). Callers wanting the full union
 * pass `includeArchived: true`.
 */
import { api } from '../../shared/api/client'

export async function listTags(includeArchived = false): Promise<string[]> {
  const result = await api.GET('/tags', {
    params: {
      query: includeArchived ? { include_archived: true } : {},
    },
  })
  const r = result as { data?: string[]; error?: unknown }
  if (r.error) throw r.error
  return r.data ?? []
}
