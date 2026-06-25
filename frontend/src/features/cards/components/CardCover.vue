<script setup lang="ts">
/**
 * `<CardCover>` — renders a card thumbnail.
 *
 * Decoupled from the parent so the homepage grid, hero, and admin table
 * all use the same fallback rules. URL passes through `CSS.escape` to
 * defeat the legacy escaping bug (PROJECT_NOTES 坑#5).
 */
import { computed } from 'vue'

const props = defineProps<{
  /** Public URL like `/covers/<id>.png?v=12345`, or null/'' when missing. */
  cover?: string | null
  /** Card title; rendered as the textual fallback when no cover exists. */
  title: string
  /** Storage type — drives the gradient palette on the fallback. */
  category: 'external' | 'local'
}>()

/**
 * Wrap a URL for safe use inside CSS `url(...)`. `CSS.escape` escapes
 * tokens (good for selectors) but not URL bodies — for that we wrap in
 * double quotes and escape any embedded double quotes/backslashes.
 */
function cssUrl(url: string): string {
  const safe = url.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
  return `url("${safe}")`
}

const hasImage = computed(() => !!props.cover)
const backgroundStyle = computed(() =>
  hasImage.value && props.cover
    ? { backgroundImage: cssUrl(props.cover) }
    : undefined,
)
</script>

<template>
  <div
    class="card-cover"
    :class="[category, hasImage ? 'has-image' : 'no-image']"
  >
    <div
      v-if="hasImage"
      class="cover-media-wrap"
      :style="backgroundStyle"
      role="img"
      :aria-label="title"
    />
    <div v-else class="cover-text-surface">
      <div class="cover-text-title">{{ title }}</div>
    </div>
    <div class="cover-orb" aria-hidden="true" />
  </div>
</template>
