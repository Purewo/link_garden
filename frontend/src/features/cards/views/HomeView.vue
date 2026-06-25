<script setup lang="ts">
/**
 * `HomeView` — public landing page.
 *
 * The chrome (sidebar, search, category strip) lives in
 * `<CardFilters>`, the hero in `<HeroBanner>`, and the list in
 * `<CardGrid>`. `useFilters()` keeps the URL ↔ store binding alive and
 * triggers a re-fetch whenever a filter changes. We render archived
 * cards as a public visitor only when `?include_archived=1` is set
 * (the server enforces this for unauthenticated callers).
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import HeroBanner from '../components/HeroBanner.vue'
import CardFilters from '../components/CardFilters.vue'
import CardGrid from '../components/CardGrid.vue'
import TagCloud from '../../tags/components/TagCloud.vue'
import { useCardsStore } from '../store'
import { useFilters } from '../composables/useFilters'
import type { CardListItem } from '../../../shared/types/domain'

const router = useRouter()
const store = useCardsStore()

// `useFilters` binds the URL ↔ store and runs `fetchList` once on mount
// (immediate watcher), so we don't trigger a duplicate fetch here.
useFilters()

const groupLabel = computed(() => store.filters.group ?? '全部')

function onSelect(card: CardListItem): void {
  // External cards open from `<CardItem>` directly via window.open;
  // any select event reaching us is a local card we need to route to.
  // We use the slug (URL handle) — the server stays the source of
  // truth for slug ↔ id mapping.
  void router.push(`/card/${card.slug}`)
}
</script>

<template>
  <section class="home-layout">
    <aside class="sidebar">
      <div class="side-card profile-card">
        <div class="profile-glow" aria-hidden="true"></div>
        <img class="profile-avatar real-profile-avatar" src="/images/avatar.jpg" alt="Link Garden 头像" />
        <h2>Link Garden</h2>
        <p>技术稍后阅读、灵感收纳、个人笔记花园。</p>
        <div class="profile-stats">
          <div>
            <strong>{{ store.list.length }}</strong>
            <span>卡片</span>
          </div>
          <div>
            <strong>{{ store.localCount }}</strong>
            <span>本站文</span>
          </div>
        </div>
      </div>

      <CardFilters />
      <TagCloud />
    </aside>

    <div class="content-panel">
      <HeroBanner />
      <section v-if="store.filters.group" class="channel-banner">
        <div class="channel-copy">
          <h3>{{ groupLabel }}</h3>
          <p>已筛选 {{ store.filteredCount }} 篇</p>
        </div>
      </section>

      <section class="content-section">
        <div class="section-strip">
          <div class="section-strip-left">
            <span class="section-dot" aria-hidden="true"></span>
            <h3>{{ groupLabel }}</h3>
          </div>
          <div class="section-strip-right">
            <span class="section-total">{{ store.list.length }} 篇</span>
          </div>
        </div>

        <p v-if="store.loading" class="loading-state">加载中…</p>
        <CardGrid
          v-else
          :items="store.list"
          mode="public"
          :empty-message="store.error ? '加载失败，请稍后重试。' : '暂时还没有内容。'"
          @select="onSelect"
        />
      </section>
    </div>
  </section>
</template>
