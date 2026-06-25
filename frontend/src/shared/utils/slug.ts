/**
 * Client-side slug preview. The server is the source of truth on POST; this is
 * here for the publish form's live preview only. Mirrors backend rules:
 *   - lowercase ASCII letters/digits + CJK characters
 *   - whitespace + most punctuation collapse to a single `-`
 *   - leading/trailing `-` trimmed
 *   - falls back to a short anonymous handle when the input has no kept chars
 */
const KEEP_RE = /[^a-z0-9一-鿿]+/gi

export function slugifyPreview(input: string): string {
  if (!input) return ''
  const lowered = input.normalize('NFKC').toLowerCase()
  const dashed = lowered.replace(KEEP_RE, '-')
  const trimmed = dashed.replace(/^-+|-+$/g, '')
  if (trimmed.length === 0) return 'article'
  return trimmed.slice(0, 80)
}
