<script setup lang="ts">
/**
 * `<ArticleHero>` — top banner of the card detail view.
 *
 * Uses the card's own cover for the background (PROJECT_NOTES rule:
 * the detail page never reuses the homepage hero). When `cover` is
 * absent we fall back to a category-tinted gradient so the page still
 * has visual identity. URL escaped for safe inline CSS use.
 */
import { computed } from 'vue'
import { formatDate } from '../../../shared/utils/date'
import type { CardDetail } from '../../../shared/types/domain'

const props = defineProps<{
  card: CardDetail
}>()

function cssUrl(url: string): string {
  const safe = url.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
  return `url("${safe}")`
}

const heroStyle = computed(() => {
  if (!props.card.cover) return undefined
  return {
    backgroundImage:
      `linear-gradient(180deg, rgba(6,8,18,.08), rgba(6,8,18,.42)), ${cssUrl(props.card.cover)}`,
  }
})

const dateLabel = computed(() => formatDate(props.card.created_at))
</script>

<template>
  <section
    class="article-hero bloglike-hero"
    :class="{ 'no-cover': !card.cover }"
    :style="heroStyle"
  >
    <div class="article-hero-overlay" aria-hidden="true"></div>
    <div class="bloglike-hero-inner">
      <div class="hero-left-copy">
        <h1>{{ card.title }}</h1>
        <div class="hero-info-row">
          <span>{{ dateLabel }}</span>
          <span v-if="card.group">{{ card.group }}</span>
          <span v-for="tag in card.tags" :key="tag" class="hero-tag">#{{ tag }}</span>
        </div>
      </div>
    </div>
  </section>
</template>
