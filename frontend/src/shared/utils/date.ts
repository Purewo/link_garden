/**
 * Date helpers. The backend emits ISO-8601 with timezone; we present locale
 * strings to the user. Falls back gracefully when the input is missing or
 * malformed (legacy date-only entries pre-migration).
 */
const DEFAULT_LOCALE = 'zh-CN'

export function formatDate(iso: string | null | undefined, locale = DEFAULT_LOCALE): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

export function formatDateTime(iso: string | null | undefined, locale = DEFAULT_LOCALE): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
