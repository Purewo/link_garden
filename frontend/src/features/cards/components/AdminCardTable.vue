<script setup lang="ts">
/**
 * AdminCardTable — sortable, searchable list of cards for the admin shell.
 *
 * Pure presentation: takes `items: CardListItem[]`, emits row-level actions.
 * The delete button is hidden by default per PROJECT_NOTES; pass
 * `:show-delete="true"` to expose it.
 */
import { computed, ref } from 'vue'
import type { CardListItem } from '@/shared/types/domain'

const props = withDefaults(
  defineProps<{
    items: CardListItem[]
    loading?: boolean
    showDelete?: boolean
  }>(),
  { loading: false, showDelete: false },
)

const emit = defineEmits<{
  (e: 'edit', item: CardListItem): void
  (e: 'archive', item: CardListItem): void
  (e: 'delete', item: CardListItem): void
}>()

type SortKey = 'created_at' | 'title' | 'category' | 'archived'
type SortDir = 'asc' | 'desc'

const sortKey = ref<SortKey>('created_at')
const sortDir = ref<SortDir>('desc')
const keyword = ref('')

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  let rows = props.items
  if (kw) {
    rows = rows.filter(
      (row) =>
        row.title.toLowerCase().includes(kw) ||
        (row.tags ?? []).some((tag) => tag.toLowerCase().includes(kw)),
    )
  }
  return [...rows].sort((a, b) => {
    const dir = sortDir.value === 'asc' ? 1 : -1
    const av = a[sortKey.value]
    const bv = b[sortKey.value]
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    if (av < bv) return -1 * dir
    if (av > bv) return 1 * dir
    return 0
  })
})

function setSort(key: SortKey) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'desc'
  }
}

function categoryLabel(cat: string | null | undefined): string {
  return cat === 'external' ? '外部' : '本站'
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return ''
  // The iso8601 emitted by FastAPI is parseable by Date directly.
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toISOString().slice(0, 10)
}
</script>

<template>
  <section class="admin-card-table">
    <header class="admin-card-table__bar">
      <input
        v-model="keyword"
        class="admin-card-table__search"
        placeholder="搜索标题或标签"
      />
      <span v-if="loading" class="admin-card-table__loading">加载中…</span>
      <span v-else class="admin-card-table__count">共 {{ filtered.length }} 篇</span>
    </header>

    <table class="admin-card-table__table">
      <thead>
        <tr>
          <th>序号</th>
          <th class="sortable" @click="setSort('title')">
            标题
            <small v-if="sortKey === 'title'">{{ sortDir === 'asc' ? '↑' : '↓' }}</small>
          </th>
          <th>标签</th>
          <th class="sortable" @click="setSort('category')">
            类型
            <small v-if="sortKey === 'category'">{{ sortDir === 'asc' ? '↑' : '↓' }}</small>
          </th>
          <th>封面</th>
          <th class="sortable" @click="setSort('created_at')">
            创建时间
            <small v-if="sortKey === 'created_at'">{{ sortDir === 'asc' ? '↑' : '↓' }}</small>
          </th>
          <th class="sortable" @click="setSort('archived')">
            状态
            <small v-if="sortKey === 'archived'">{{ sortDir === 'asc' ? '↑' : '↓' }}</small>
          </th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in filtered" :key="row.id">
          <td>{{ index + 1 }}</td>
          <td class="title-cell">{{ row.title }}</td>
          <td>{{ (row.tags ?? []).join(' / ') }}</td>
          <td>
            <span
              class="table-pill"
              :class="row.category === 'external' ? 'external' : 'local'"
            >
              {{ categoryLabel(row.category) }}
            </span>
          </td>
          <td>
            <div class="table-cover" :class="{ empty: !row.cover }">
              <img v-if="row.cover" :src="row.cover" alt="cover" />
              <span v-else>无</span>
            </div>
          </td>
          <td>{{ fmtDate(row.created_at) }}</td>
          <td>
            <span
              class="table-pill"
              :class="row.archived ? 'archived' : 'active'"
            >
              {{ row.archived ? '已下架' : '在线' }}
            </span>
          </td>
          <td>
            <div class="table-actions">
              <button type="button" class="link-btn" @click="emit('edit', row)">
                编辑
              </button>
              <button
                type="button"
                class="link-btn"
                @click="emit('archive', row)"
              >
                {{ row.archived ? '恢复' : '下架' }}
              </button>
              <button
                v-if="showDelete"
                type="button"
                class="link-btn danger"
                @click="emit('delete', row)"
              >
                删除
              </button>
            </div>
          </td>
        </tr>
        <tr v-if="!filtered.length">
          <td colspan="8" class="admin-card-table__empty">
            {{ loading ? '加载中…' : '还没有文章' }}
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.admin-card-table {
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--lg-surface, #1c2230);
  border: 1px solid var(--lg-border, #2a2f3a);
  border-radius: 12px;
  padding: 12px;
}
.admin-card-table__bar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.admin-card-table__search {
  flex: 1 1 320px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--lg-border, #2a2f3a);
  background: var(--lg-surface-2, #161a23);
  color: var(--lg-text, #e6ebf5);
  font-size: 13px;
}
.admin-card-table__count,
.admin-card-table__loading {
  color: var(--lg-text-muted, #8a93a3);
  font-size: 12px;
}
.admin-card-table__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.admin-card-table__table th,
.admin-card-table__table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--lg-border, #2a2f3a);
  text-align: left;
  color: var(--lg-text, #d8dee9);
  vertical-align: middle;
}
.admin-card-table__table th {
  color: var(--lg-text-muted, #8a93a3);
  font-weight: 500;
  user-select: none;
}
.admin-card-table__table th.sortable {
  cursor: pointer;
}
.title-cell {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.table-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  background: var(--lg-surface-2, #161a23);
}
.table-pill.external {
  color: #f5b88a;
}
.table-pill.local {
  color: #8ad0ff;
}
.table-pill.archived {
  color: #ff8c8c;
}
.table-pill.active {
  color: #8ee29c;
}
.table-cover {
  width: 56px;
  height: 36px;
  border-radius: 4px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--lg-surface-2, #161a23);
}
.table-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.table-cover.empty span {
  font-size: 11px;
  color: var(--lg-text-muted, #8a93a3);
}
.table-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.link-btn {
  background: transparent;
  border: none;
  color: var(--lg-accent, #4fa3ff);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}
.link-btn.danger {
  color: var(--lg-danger, #ff6b6b);
}
.admin-card-table__empty {
  text-align: center;
  color: var(--lg-text-muted, #8a93a3);
  padding: 24px 0;
}
</style>
