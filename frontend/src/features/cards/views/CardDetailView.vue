<script setup lang="ts">
/**
 * `CardDetailView` — public detail page for local cards.
 *
 * - Uses the card's own cover for the hero (per PROJECT_NOTES).
 * - Trusts the server-sanitised `body_html` via `<ArticleBody>`.
 * - 404s when the slug is missing or the card is archived (server
 *   returns `card_not_found` for unauthenticated callers; we surface
 *   that as the "not found" view rather than redirecting).
 * - No right-side TOC, no back button — both forbidden by PROJECT_NOTES.
 */
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ArticleHero from '../components/ArticleHero.vue'
import ArticleBody from '../components/ArticleBody.vue'
import { useCardsStore } from '../store'
import type { CardDetail } from '../../../shared/types/domain'

const route = useRoute()
const store = useCardsStore()

const card = ref<CardDetail | null>(null)
const loading = ref(false)
const notFound = ref(false)
const errorMessage = ref<string | null>(null)

async function load(slug: string): Promise<void> {
  loading.value = true
  notFound.value = false
  errorMessage.value = null
  card.value = null
  try {
    const detail = await store.fetchDetail(slug)
    card.value = detail
  } catch (err) {
    const code = (err as { code?: string } | null)?.code
    if (code === 'card_not_found') {
      notFound.value = true
    } else {
      errorMessage.value =
        (err as { message?: string } | null)?.message ?? '加载失败，请稍后再试。'
    }
  } finally {
    loading.value = false
  }
}

watch(
  () => route.params.slug,
  (slug) => {
    if (typeof slug === 'string' && slug.length > 0) {
      void load(slug)
    }
  },
  { immediate: true },
)
</script>

<template>
  <section class="article-detail-page">
    <p v-if="loading" class="loading-state">加载中…</p>

    <div v-else-if="notFound" class="not-found-card">
      <h2>找不到这篇内容</h2>
      <p>它可能已被归档或链接已过期。</p>
      <RouterLink to="/" class="link-btn">回到首页</RouterLink>
    </div>

    <div v-else-if="errorMessage" class="error-card">
      <h2>加载失败</h2>
      <p>{{ errorMessage }}</p>
    </div>

    <template v-else-if="card">
      <ArticleHero :card="card" />
      <section class="detail article-detail-body">
        <ArticleBody v-if="card.body_html" :html="card.body_html" />
        <p v-else class="empty-state">这张卡片没有正文内容。</p>
      </section>
    </template>
  </section>
</template>
