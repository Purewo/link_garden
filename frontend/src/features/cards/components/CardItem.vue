<script setup lang="ts">
/**
 * `<CardItem>` — single tile in the homepage grid.
 *
 * Owns the hover behaviour from PROJECT_NOTES (#card-hover): the cover
 * image scales and the shadow grows, but the card itself does not
 * translate. Activation always emits `select`; the parent decides
 * whether to route or open an external URL (the list shape doesn't
 * carry `url` so external resolution has to consult the detail cache).
 */
import { computed } from 'vue'
import CardCover from './CardCover.vue'
import { formatDate } from '../../../shared/utils/date'
import type { CardListItem } from '../../../shared/types/domain'

/**
 * The list shape from the server omits `url` (it lives on `CardRead`),
 * but tests and admin code commonly hand us a card with an extra
 * `url` field. We keep the prop loose so both shapes type-check.
 */
type CardItemLike = CardListItem & { url?: string | null }

const props = defineProps<{
  card: CardItemLike
  /** When true, render admin trailing actions via the named slot. */
  admin?: boolean
}>()

const emit = defineEmits<{
  (e: 'select', card: CardItemLike): void
}>()

const dateLabel = computed(() => formatDate(props.card.created_at))

function onActivate(): void {
  if (props.card.category === 'external' && props.card.url) {
    window.open(props.card.url, '_blank', 'noopener,noreferrer')
    return
  }
  emit('select', props.card)
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    onActivate()
  }
}
</script>

<template>
  <article
    class="card layered-card article-card"
    :class="{ 'is-archived': card.archived }"
    role="link"
    tabindex="0"
    @click="onActivate"
    @keydown="onKey"
  >
    <CardCover :cover="card.cover" :title="card.title" :category="card.category" />
    <div class="card-body article-body">
      <div class="article-time">发布于 {{ dateLabel }}</div>
      <h3>{{ card.title }}</h3>
      <p v-if="card.summary" class="article-summary">{{ card.summary }}</p>
      <div v-if="card.tags?.length" class="meta article-tags">
        <span v-for="tag in card.tags" :key="tag" class="tag pill-tag">{{ tag }}</span>
      </div>
      <div v-if="admin" class="card-actions">
        <slot name="actions" :card="card" />
      </div>
    </div>
  </article>
</template>
