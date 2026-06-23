<template>
  <section class="home-layout">
    <aside class="sidebar">
      <div class="side-card profile-card">
        <div class="profile-glow"></div>
        <img class="profile-avatar real-profile-avatar" src="/images/avatar.jpg" alt="净界头像" />
        <h2>Link Garden</h2>
        <p>技术稍后阅读、灵感收纳、个人笔记花园。</p>
        <div class="profile-stats">
          <div>
            <strong>{{ cards.length }}</strong>
            <span>卡片</span>
          </div>
          <div>
            <strong>{{ tags.length }}</strong>
            <span>标签</span>
          </div>
          <div>
            <strong>{{ localCount }}</strong>
            <span>本站文</span>
          </div>
        </div>
      </div>

      <div class="side-card search-card">
        <div class="search-head">
          <h3>搜索</h3>
        </div>
        <div class="search-box">
          <input v-model="keyword" placeholder="搜索标题 / 标签 / 灵感关键词" />
          <button class="search-btn" @click="noopSearch">搜索</button>
        </div>
      </div>

      <section class="category-deck sidebar-category-deck">
        <button
          v-for="item in categories"
          :key="item.key"
          class="category-card"
          :class="[item.key, { active: activeCategory === item.key }]"
          type="button"
          @click="activeCategory = item.key"
        >
          <h3>{{ item.label }}</h3>
          <p>{{ item.desc }}</p>
        </button>
      </section>
    </aside>

    <div class="content-panel">
      <section v-if="activeCategory !== 'default'" class="channel-banner">
        <div class="channel-icon">{{ currentCategory.icon }}</div>
        <div class="channel-copy">
          <h3>{{ currentCategory.bannerTitle }}</h3>
          <p>{{ currentCategory.bannerDesc }}</p>
        </div>
      </section>

      <section class="content-section">
        <div class="section-strip">
          <div class="section-strip-left">
            <span class="section-dot"></span>
            <h3>{{ currentCategory.label }}</h3>
          </div>
          <div class="section-strip-right">
            <span class="section-total">{{ filteredCards.length }} 篇</span>
            <span class="section-more">MORE</span>
          </div>
        </div>

        <div class="grid content-grid" :class="[`layout-${activeCategory}`, { 'tech-mode': activeCategory === 'tech' }]">
          <article v-for="card in filteredCards" :key="card.id" class="card layered-card article-card" @click="openCard(card)">
            <div class="card-cover" :class="[card.category, { 'has-image': !!card.cover, 'no-image': !card.cover }]">
              <div v-if="card.cover" class="cover-media-wrap">
                <img :src="card.cover" :alt="card.title" class="cover-media" />
              </div>
              <div v-else class="cover-text-surface">
                <div class="cover-text-title">{{ card.title }}</div>
              </div>
              <div class="cover-orb"></div>
            </div>
            <div class="card-body article-body">
              <div class="article-time">🕒 发布于 {{ card.created_at }} 23:39:42</div>
              <h3>{{ card.title }}</h3>
              <div class="article-stats">
                <span>🔥 11 热度</span>
                <span>💬 0 条评论</span>
                <span>🧡 0 点赞</span>
              </div>
              <p>{{ card.summary }}</p>
              <div class="meta article-tags">
                <span v-for="tag in card.tags" :key="tag" class="tag pill-tag">🏷 {{ tag }}</span>
              </div>
            </div>
          </article>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const cards = ref([])
const tags = ref([])
const keyword = ref('')
const activeCategory = ref('default')
const apiBase = `/api`

const categories = [
  {
    key: 'tech',
    label: '技术类',
    desc: '收藏技术文章、工具、框架、设计灵感和个人技术笔记。',
    icon: '🔊',
    bannerTitle: '技术发现',
    bannerDesc: '这一栏用来放真正值得回头再看的技术内容。',
  },
  {
    key: 'notes',
    label: '随笔类',
    desc: '以后放你的随笔、想法、个人感受和慢慢长出来的文字。',
    icon: '✍️',
    bannerTitle: '随笔记录',
    bannerDesc: '这里以后会更私人，也更像慢慢生长的个人博客。',
  },
  {
    key: 'life',
    label: '生活类',
    desc: '留给未来：生活记录、好物、灵感碎片和你想慢慢整理的东西。',
    icon: '☕',
    bannerTitle: '生活归档',
    bannerDesc: '一些不必太技术、但依然值得留下来的日常片段。',
  },
]

const currentCategory = computed(() => categories.find(item => item.key === activeCategory.value) || { label: '技术类', icon: '🔊', bannerTitle: '技术发现', bannerDesc: '这一栏用来放真正值得回头再看的技术内容。' })

onMounted(async () => {
  try {
    const [cardsRes, tagsRes] = await Promise.all([
      axios.get(`${apiBase}/cards`),
      axios.get(`${apiBase}/tags`),
    ])
    cards.value = cardsRes.data
    tags.value = tagsRes.data
  } catch (error) {
    console.error('首页数据加载失败', error)
  }
})

const localCount = computed(() => cards.value.filter(card => card.category === 'local').length)

const filteredCards = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return cards.value.filter(card => {
    const hitKeyword = !kw || card.title.toLowerCase().includes(kw) || (card.tags || []).some(t => t.toLowerCase().includes(kw))
    return hitKeyword
  })
})

function noopSearch() {}

function openCard(card) {
  if (card.category === 'external') {
    window.open(card.url, '_blank', 'noopener,noreferrer')
  } else {
    router.push(`/card/${card.id}`)
  }
}
</script>
