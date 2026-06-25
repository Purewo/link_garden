<script setup lang="ts">
/**
 * AdminPublishView — create + edit a single card.
 *
 * Route signature:
 *   /admin/publish              → create mode
 *   /admin/publish/:id          → edit mode (fetches the card by uuid)
 *
 * Composition:
 *   useCardForm()    — form state, validation, dirty tracking, submit
 *   PublishForm.vue  — UI shell driven by the form controller
 *
 * After a successful create, the route is replaced to the edit variant so
 * subsequent cover uploads have a valid cardId to target.
 */
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PublishForm from '@/features/cards/components/PublishForm.vue'
import { useCardForm } from '@/features/cards/composables/useCardForm'
import { useCardsStore } from '@/features/cards/store'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const cardsStore = useCardsStore()
const uiStore = useUiStore()

const formCtl = useCardForm()
const loading = ref(false)

async function hydrateFromRoute() {
  const id = route.params.id
  if (!id || typeof id !== 'string') {
    formCtl.reset()
    return
  }
  loading.value = true
  try {
    // The store's `fetchDetail` is keyed by slug (the public lookup path).
    // For admin edits the URL carries the immutable card id, so we resolve
    // it to a slug via the already-loaded list. If the list isn't loaded
    // yet, fetch it once first.
    if (!cardsStore.list.length) {
      cardsStore.setFilter({ includeArchived: true })
      await cardsStore.fetchList()
    }
    const summary = cardsStore.list.find((c) => c.id === id)
    if (!summary) {
      throw new Error('文章不存在或已删除')
    }
    const detail = await cardsStore.fetchDetail(summary.slug)
    formCtl.loadFromDetail(detail)
  } catch (err) {
    uiStore.pushToast({
      kind: 'error',
      title: '载入失败',
      message: err instanceof Error ? err.message : String(err),
    })
  } finally {
    loading.value = false
  }
}

onMounted(hydrateFromRoute)
watch(() => route.params.id, hydrateFromRoute)

async function handleSubmit() {
  try {
    const wasEdit = formCtl.isEdit.value
    const detail = await formCtl.submit()
    uiStore.pushToast({
      kind: 'success',
      title: wasEdit ? '已保存' : '已发布',
      message: detail.title,
    })
    if (!wasEdit) {
      // After create, swap to edit-by-id so a follow-up cover upload has
      // a real cardId to bind to.
      router.replace({ name: 'admin-edit', params: { id: detail.id } })
    }
  } catch (err) {
    uiStore.pushToast({
      kind: 'error',
      title: '提交失败',
      message: err instanceof Error ? err.message : String(err),
    })
  }
}

function handleCancel() {
  if (formCtl.dirty.value) {
    const confirmed = window.confirm('当前修改未保存，确认离开？')
    if (!confirmed) return
  }
  router.push({ name: 'admin-cards' })
}

function handleCoverError(message: string) {
  uiStore.pushToast({ kind: 'error', title: '封面错误', message })
}
</script>

<template>
  <section class="admin-publish-view">
    <div v-if="loading" class="admin-publish-view__loading">载入中…</div>
    <PublishForm
      v-else
      :form-ctl="formCtl"
      @submit="handleSubmit"
      @cancel="handleCancel"
      @cover-error="handleCoverError"
    />
  </section>
</template>

<style scoped>
.admin-publish-view {
  padding: 24px;
}
.admin-publish-view__loading {
  padding: 48px;
  text-align: center;
  color: var(--lg-text-muted, #8a93a3);
}
</style>
