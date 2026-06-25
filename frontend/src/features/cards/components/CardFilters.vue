<script setup lang="ts">
/**
 * `<CardFilters>` — filter chips + keyword input bound to the cards
 * store. The store is the single source of truth; the component reads
 * from `store.filters` and writes via `store.setFilter`. Deep-link
 * persistence is handled by `useFilters()` upstream.
 */
import { computed } from 'vue'
import { useCardsStore } from '../store'

const store = useCardsStore()

interface CategoryOption {
  key: 'tech' | 'notes' | 'life' | null
  label: string
  desc: string
  /** Maps the UI key to the backend's `group` field. */
  group: '技术类' | '随笔类' | '生活类' | null
}

const categories: CategoryOption[] = [
  { key: null, label: '全部', desc: '显示所有内容', group: null },
  {
    key: 'tech',
    label: '技术类',
    desc: '收藏技术文章、工具、框架、设计灵感和个人技术笔记。',
    group: '技术类',
  },
  {
    key: 'notes',
    label: '随笔类',
    desc: '随笔、想法、个人感受和慢慢长出来的文字。',
    group: '随笔类',
  },
  {
    key: 'life',
    label: '生活类',
    desc: '生活记录、好物、灵感碎片和你想慢慢整理的东西。',
    group: '生活类',
  },
]

const activeKey = computed<CategoryOption['key']>(() => {
  const match = categories.find((c) => c.group === store.filters.group)
  return match ? match.key : null
})

function selectCategory(option: CategoryOption): void {
  store.setFilter({ group: option.group })
}

function onKeywordInput(e: Event): void {
  const target = e.target as HTMLInputElement
  store.setFilter({ q: target.value })
}

function clearTag(): void {
  store.setFilter({ tag: null })
}
</script>

<template>
  <section class="card-filters">
    <div class="search-card side-card">
      <div class="search-head">
        <h3>搜索</h3>
      </div>
      <div class="search-box">
        <input
          :value="store.filters.q"
          placeholder="搜索标题 / 标签 / 灵感关键词"
          @input="onKeywordInput"
        />
      </div>
      <div v-if="store.filters.tag" class="active-tag">
        已选标签：
        <span class="tag pill-tag">{{ store.filters.tag }}</span>
        <button type="button" class="link-btn" @click="clearTag">清除</button>
      </div>
    </div>

    <div class="category-deck sidebar-category-deck">
      <button
        v-for="item in categories"
        :key="item.key ?? 'all'"
        type="button"
        class="category-card"
        :class="[
          item.key ?? 'all',
          { active: activeKey === item.key },
        ]"
        @click="selectCategory(item)"
      >
        <h3>{{ item.label }}</h3>
        <p>{{ item.desc }}</p>
      </button>
    </div>
  </section>
</template>
