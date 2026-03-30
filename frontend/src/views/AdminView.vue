<template>
  <section class="admin-page-wrap">
    <div class="admin-global-back-row">
      <router-link class="admin-global-back" to="/">
        <span class="admin-global-back-icon">⚡</span>
        <span>回到前台</span>
      </router-link>
    </div>

    <section class="admin-shell">
      <aside class="admin-sidebar">
        <div class="admin-brand-card">
          <p class="admin-kicker">ADMIN CONSOLE</p>
          <h2>后台管理</h2>
          <p>管理文章、分类与发布流程。风格延续主站，但更偏控制台感。</p>
        </div>

        <nav class="admin-menu">
          <button class="admin-menu-item active">
            <span>📝</span>
            <span>文章管理</span>
          </button>
          <button class="admin-menu-item">
            <span>🗂</span>
            <span>分类管理</span>
          </button>
          <button class="admin-menu-item">
            <span>⚙️</span>
            <span>站点设置</span>
          </button>
        </nav>
      </aside>

      <div class="admin-main">
        <header class="admin-topbar">
          <div>
            <p class="admin-kicker">ARTICLE CONTROL</p>
            <h1>文章管理</h1>
          </div>
          <div class="admin-top-actions">
            <button class="admin-action ghost" @click="resetFilters">清空筛选</button>
            <router-link class="admin-action primary admin-link-btn" to="/admin/publish">新增文章</router-link>
          </div>
        </header>

        <section class="admin-filter-bar">
          <input v-model="filters.keyword" placeholder="文章标题" />
          <select v-model="filters.kind">
            <option value="">所有类型</option>
            <option value="external">外部文章</option>
            <option value="local">本站文章</option>
          </select>
          <input v-model="filters.tag" placeholder="标签关键词" />
          <button class="admin-action primary" @click="noopSearch">搜索</button>
        </section>

        <section class="admin-table-card">
          <table class="admin-table">
            <thead>
              <tr>
                <th>序号</th>
                <th>标题</th>
                <th>标签</th>
                <th>类型</th>
                <th>封面</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in filteredRows" :key="row.id">
                <td>{{ index + 1 }}</td>
                <td class="title-cell">{{ row.title }}</td>
                <td>{{ (row.tags || []).join(' / ') }}</td>
                <td>
                  <span class="table-pill" :class="row.category === 'external' ? 'external' : 'local'">
                    {{ row.category === 'external' ? '外部' : '本站' }}
                  </span>
                </td>
                <td>
                  <div class="table-cover" :class="{ empty: !row.cover }">
                    <img v-if="row.cover" :src="row.cover" alt="cover" />
                    <span v-else>无</span>
                  </div>
                </td>
                <td>{{ row.created_at }}</td>
                <td>
                  <div class="table-actions">
                    <router-link :to="`/admin/publish?id=${row.id}`">编辑</router-link>
                    <a href="#" @click.prevent="noopSearch">下架</a>
                  </div>
                </td>
              </tr>
              <tr v-if="!filteredRows.length">
                <td colspan="7" class="empty-table">还没有文章</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'

const apiBase = `${window.location.protocol}//${window.location.hostname}:5001`
const rows = ref([])
const filters = reactive({ keyword: '', kind: '', tag: '' })

async function loadRows() {
  const res = await axios.get(`${apiBase}/api/cards`)
  rows.value = res.data
}

onMounted(loadRows)

const filteredRows = computed(() => {
  const kw = filters.keyword.trim().toLowerCase()
  const tagKw = filters.tag.trim().toLowerCase()
  return rows.value.filter((row) => {
    const hitKeyword = !kw || row.title.toLowerCase().includes(kw)
    const hitKind = !filters.kind || row.category === filters.kind
    const hitTag = !tagKw || (row.tags || []).some((tag) => tag.toLowerCase().includes(tagKw))
    return hitKeyword && hitKind && hitTag
  })
})

function resetFilters() {
  filters.keyword = ''
  filters.kind = ''
  filters.tag = ''
}

function noopSearch() {}
</script>
