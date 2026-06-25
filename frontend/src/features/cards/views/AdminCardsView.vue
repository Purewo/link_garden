<script setup lang="ts">
/**
 * AdminCardsView — admin landing page; lists all cards (including archived),
 * lets the operator edit, archive/unarchive, and (when explicitly enabled)
 * delete. Routes to /admin/publish/:id for editing.
 */
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AdminCardTable from '@/features/cards/components/AdminCardTable.vue'
import { useCardsStore } from '@/features/cards/store'
import { useUiStore } from '@/stores/ui'
import { useAuthStore } from '@/features/auth/store'
import type { CardListItem } from '@/shared/types/domain'

const router = useRouter()
const cardsStore = useCardsStore()
const uiStore = useUiStore()
const authStore = useAuthStore()

const items = computed<CardListItem[]>(() => cardsStore.list)
const loading = computed(() => cardsStore.loading)
const isAdmin = computed(() => authStore.isAdmin)

onMounted(async () => {
  // Admin view always wants archived cards visible.
  cardsStore.setFilter({ includeArchived: true })
  try {
    await cardsStore.fetchList()
  } catch (err) {
    uiStore.pushToast({
      kind: 'error',
      title: '加载失败',
      message: err instanceof Error ? err.message : String(err),
    })
  }
})

function goCreate() {
  router.push({ name: 'admin-publish' })
}

function onEdit(row: CardListItem) {
  router.push({ name: 'admin-edit', params: { id: row.id } })
}

async function onArchive(row: CardListItem) {
  try {
    await cardsStore.archive(row.id, !row.archived)
    uiStore.pushToast({
      kind: 'success',
      title: row.archived ? '已恢复' : '已下架',
      message: row.title,
    })
  } catch (err) {
    uiStore.pushToast({
      kind: 'error',
      title: '操作失败',
      message: err instanceof Error ? err.message : String(err),
    })
  }
}

async function onDelete(row: CardListItem) {
  if (!isAdmin.value) return
  const confirmed = window.confirm(`确认删除《${row.title}》？该操作不可撤销。`)
  if (!confirmed) return
  try {
    await cardsStore.remove(row.id)
    uiStore.pushToast({
      kind: 'success',
      title: '已删除',
      message: row.title,
    })
  } catch (err) {
    uiStore.pushToast({
      kind: 'error',
      title: '删除失败',
      message: err instanceof Error ? err.message : String(err),
    })
  }
}

async function refresh() {
  try {
    await cardsStore.fetchList()
  } catch (err) {
    uiStore.pushToast({
      kind: 'error',
      title: '刷新失败',
      message: err instanceof Error ? err.message : String(err),
    })
  }
}
</script>

<template>
  <section class="admin-cards-view">
    <header class="admin-cards-view__head">
      <div>
        <p class="admin-cards-view__kicker">ARTICLE CONTROL</p>
        <h1>文章管理</h1>
      </div>
      <div class="admin-cards-view__actions">
        <button class="admin-action ghost" type="button" @click="refresh">
          刷新
        </button>
        <button class="admin-action primary" type="button" @click="goCreate">
          新增文章
        </button>
      </div>
    </header>

    <AdminCardTable
      :items="items"
      :loading="loading"
      :show-delete="false"
      @edit="onEdit"
      @archive="onArchive"
      @delete="onDelete"
    />
  </section>
</template>

<style scoped>
.admin-cards-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
}
.admin-cards-view__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 12px;
}
.admin-cards-view__kicker {
  color: var(--lg-text-muted, #8a93a3);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin: 0;
}
.admin-cards-view h1 {
  margin: 4px 0 0 0;
  font-size: 24px;
}
.admin-cards-view__actions {
  display: flex;
  gap: 8px;
}
.admin-action {
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid var(--lg-border, #2a2f3a);
  background: var(--lg-surface, #1c2230);
  color: var(--lg-text, #d8dee9);
  cursor: pointer;
  font-size: 13px;
}
.admin-action.primary {
  background: var(--lg-accent, #4fa3ff);
  color: #0b0d12;
  border-color: transparent;
}
.admin-action.ghost {
  background: transparent;
}
</style>
