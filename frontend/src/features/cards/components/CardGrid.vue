<script setup lang="ts">
/**
 * `<CardGrid>` — dumb list component.
 *
 * Owns no fetching, no filter state. Renders whatever it is given,
 * forwards user intent up via events. The same component backs the
 * public homepage and the admin list (admin mode shows trailing
 * actions via the named `actions` slot).
 */
import CardItem from './CardItem.vue'
import type { CardListItem } from '../../../shared/types/domain'

defineProps<{
  items: CardListItem[]
  mode?: 'public' | 'admin'
  /** Optional layout hint that the CSS reads as `.layout-<key>`. */
  layout?: string
  /** Optional empty-state message. */
  emptyMessage?: string
}>()

const emit = defineEmits<{
  (e: 'select', card: CardListItem): void
}>()

function onSelect(card: CardListItem): void {
  emit('select', card)
}
</script>

<template>
  <div
    class="grid content-grid"
    :class="[layout ? `layout-${layout}` : null]"
  >
    <CardItem
      v-for="card in items"
      :key="card.id"
      :card="card"
      :admin="mode === 'admin'"
      @select="onSelect"
    >
      <template v-if="$slots.actions" #actions="slotProps">
        <slot name="actions" v-bind="slotProps" />
      </template>
    </CardItem>
    <div v-if="!items.length" class="card-grid-empty">
      {{ emptyMessage ?? '暂时还没有内容。' }}
    </div>
  </div>
</template>
