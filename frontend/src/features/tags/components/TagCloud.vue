<script setup lang="ts">
/**
 * `<TagCloud>` — renders the tag union as clickable chips.
 *
 * Clicking a tag mutates `useCardsStore.filters.tag`; the cards store
 * watcher (`useFilters`) refetches the list. The tags store is the
 * source of truth for the chip set; we treat it as read-only here.
 */
import { computed, onMounted } from 'vue'
import { useTagsStore } from '../store'
import { useCardsStore } from '../../cards/store'

const props = defineProps<{
  /** Limit how many chips to show; defaults to all. */
  limit?: number
  /** Whether to fetch on mount. */
  autoLoad?: boolean
}>()

const tagsStore = useTagsStore()
const cardsStore = useCardsStore()

const visible = computed(() =>
  props.limit ? tagsStore.tags.slice(0, props.limit) : tagsStore.tags,
)

const activeTag = computed(() => cardsStore.filters.tag)

onMounted(() => {
  if (props.autoLoad ?? true) {
    void tagsStore.fetch().catch(() => {
      // Errors are surfaced via the toast pipeline at the API layer.
    })
  }
})

function pick(tag: string): void {
  cardsStore.setFilter({ tag: cardsStore.filters.tag === tag ? null : tag })
}
</script>

<template>
  <div class="tag-cloud" v-if="visible.length">
    <button
      v-for="tag in visible"
      :key="tag"
      type="button"
      class="tag pill-tag"
      :class="{ active: activeTag === tag }"
      @click="pick(tag)"
    >
      {{ tag }}
    </button>
  </div>
</template>
