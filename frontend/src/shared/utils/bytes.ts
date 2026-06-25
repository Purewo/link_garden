/** Human-friendly byte size string. */
const UNITS = ['B', 'KiB', 'MiB', 'GiB'] as const

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '0 B'
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  const fixed = value >= 100 || unit === 0 ? value.toFixed(0) : value.toFixed(1)
  return `${fixed} ${UNITS[unit]}`
}
