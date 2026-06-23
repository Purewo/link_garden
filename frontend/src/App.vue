<template>
  <div class="app-shell">
    <div class="particles" aria-hidden="true">
      <span v-for="n in 24" :key="n" class="particle" :style="particleStyle(n)"></span>
    </div>

    <template v-if="!isAdminRoute && !isDetailRoute">
      <section class="hero-banner" :style="heroStyle">
        <header class="top-nav">
          <div class="top-nav-inner">
            <div class="brand">净界</div>
            <div class="nav-right">
              <nav class="nav-links">
                <a href="#">🏠 首页</a>
                <a href="#">📒 记录</a>
                <a href="#">💖 杂记</a>
                <a href="#">🧭 随笔</a>
                <a href="#">📷 旅拍</a>
                <a href="#">🧰 百宝箱</a>
                <a href="#">💬 留言</a>
                <a href="#">🪐 联系我</a>
                <router-link to="/admin">💻 后台</router-link>
              </nav>
              <img class="nav-avatar real-avatar" src="/images/avatar.jpg" alt="净界头像" />
            </div>
          </div>
        </header>

        <div class="hero-overlay"></div>
        <div class="hero-inner">
          <h1>技术卡片花园</h1>
          <p class="sub hero-sub">收集灵感，种下技术，等它们在未来发芽。<br />外部文章一键跳转，自己的文章留在站内慢慢长大。</p>
          <div class="hero-actions">
            <a href="#content" class="hero-btn primary" @click.prevent="scrollToContent">开始逛逛</a>
            <span class="hero-hint">是个人博客，也是技术收藏展厅</span>
          </div>
        </div>
        <div class="hero-wave" aria-hidden="true">
          <svg viewBox="0 0 1440 160" preserveAspectRatio="none">
            <path fill="rgba(11,16,32,0.98)" d="M0,128L60,117.3C120,107,240,85,360,90.7C480,96,600,128,720,133.3C840,139,960,117,1080,101.3C1200,85,1320,75,1380,69.3L1440,64L1440,160L1380,160C1320,160,1200,160,1080,160C960,160,840,160,720,160C600,160,480,160,360,160C240,160,120,160,60,160L0,160Z"></path>
          </svg>
        </div>
      </section>

      <main id="content">
        <router-view />
      </main>
    </template>

    <template v-else-if="isAdminRoute">
      <main class="admin-page-shell">
        <router-view />
      </main>
    </template>

    <template v-else>
      <main class="detail-page-shell">
        <router-view />
      </main>
    </template>

    <button v-show="showRocket" class="back-to-top" @click="scrollToTop" aria-label="回到顶部">
      🚀
    </button>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const isAdminRoute = computed(() => route.path.startsWith('/admin'))
const isDetailRoute = computed(() => route.path.startsWith('/card/'))
const showRocket = ref(false)

const heroImage = 'https://gameuniverse.top:81/d/%E7%A7%BB%E5%8A%A8%E8%B5%84%E6%BA%90/%E4%B8%AA%E4%BA%BA%E4%BA%91/%E6%89%8B%E6%9C%BA%E5%9B%BE%E7%89%87/%E3%80%90%E5%93%B2%E9%A3%8E%E5%A3%81%E7%BA%B8%E3%80%91%E6%8F%92%E7%94%BB-%E6%97%A7_%E5%87%BA%E6%B0%B4%E8%8A%99%E8%93%89.png?sign=gIKB1VBkf9P2SCYMl0XC7Hbc36v-QqgC9t9sJvqw_Nc=:0'

const heroStyle = {
  backgroundImage: `linear-gradient(180deg, rgba(7,10,20,.34) 0%, rgba(7,10,20,.58) 56%, rgba(11,16,32,.92) 100%), url("${heroImage}")`,
}

function scrollToContent() {
  const el = document.getElementById('content')
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function handleScroll() {
  showRocket.value = window.scrollY > 420
}

onMounted(() => {
  window.addEventListener('scroll', handleScroll, { passive: true })
  handleScroll()
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', handleScroll)
})

function particleStyle(n) {
  const left = (n * 37) % 100
  const top = (n * 19) % 100
  const size = 2 + (n % 4)
  const delay = (n % 7) * 0.8
  const duration = 8 + (n % 5) * 3
  const opacity = 0.16 + (n % 4) * 0.07
  const palette = [
    'rgba(0,170,255,.95)',
    'rgba(7,182,201,.92)',
    'rgba(183,148,246,.9)',
    'rgba(255,178,107,.88)',
    'rgba(255,112,166,.86)',
  ]
  const glow = palette[n % palette.length]
  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${size}px`,
    height: `${size}px`,
    animationDelay: `${delay}s`,
    animationDuration: `${duration}s`,
    opacity,
    '--particle-color': glow,
  }
}
</script>
