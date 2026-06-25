/**
 * `useTagsStore` — small in-memory cache of the tag union.
 *
 * Refetched once on the homepage mount; admin views can pass
 * `includeArchived: true` to see every tag including archived rows.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listTags } from './api'

export const useTagsStore = defineStore('tags', () => {
  const tags = ref<string[]>([])
  const loading = ref(false)
  const error = ref<unknown>(null)

  async function fetch(includeArchived = false): Promise<void> {
    loading.value = true
    error.value = null
    try {
      tags.value = await listTags(includeArchived)
    } catch (err) {
      error.value = err
      throw err
    } finally {
      loading.value = false
    }
  }

  function $reset(): void {
    tags.value = []
    loading.value = false
    error.value = null
  }

  return { tags, loading, error, fetch, $reset }
})
