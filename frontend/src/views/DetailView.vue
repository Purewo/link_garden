<template>
  <section class="article-detail-page" v-if="card">
    <section
      class="article-hero bloglike-hero"
      :class="{ 'no-cover': !card.cover }"
      :style="card.cover ? { backgroundImage: `linear-gradient(180deg, rgba(6,8,18,.08), rgba(6,8,18,.42)), url(${card.cover})` } : {}"
    >
      <div class="article-hero-overlay"></div>

      <div class="bloglike-hero-inner">
        <div class="hero-left-copy">
          <h1>{{ card.title }}</h1>
          <div class="hero-info-row">
            <span>👤 pureworld</span>
            <span>🕒 {{ card.created_at }} 13:35:55</span>
            <span>🔥 10</span>
            <span>💬 0</span>
            <span>🧡 0</span>
          </div>
        </div>
      </div>
    </section>

    <section class="detail article-detail-body">
      <article class="markdown-body article-prose" ref="articleRef" v-html="card.content_html"></article>
    </section>
  </section>
</template>

<script setup>
import axios from 'axios'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'
import { nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const card = ref(null)
const articleRef = ref(null)
const apiBase = `/api`

function decorateCodeBlocks() {
  const root = articleRef.value
  if (!root) return

  root.querySelectorAll('pre').forEach((pre) => {
    if (pre.parentElement && pre.parentElement.classList.contains('code-card')) return
    const code = pre.querySelector('code')
    if (!code) return

    hljs.highlightElement(code)

    const wrapper = document.createElement('div')
    wrapper.className = 'code-card'

    const toolbar = document.createElement('div')
    toolbar.className = 'code-toolbar'

    const dots = document.createElement('div')
    dots.className = 'code-dots'
    dots.innerHTML = '<span></span><span></span><span></span>'

    const lang = document.createElement('div')
    lang.className = 'code-lang'
    const className = Array.from(code.classList).find((cls) => cls.startsWith('language-')) || ''
    lang.textContent = className ? className.replace('language-', '').toUpperCase() : 'CODE'

    const copyBtn = document.createElement('button')
    copyBtn.className = 'code-copy'
    copyBtn.type = 'button'
    copyBtn.textContent = '复制'
    copyBtn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(code.innerText)
        copyBtn.textContent = '已复制'
        setTimeout(() => {
          copyBtn.textContent = '复制'
        }, 1400)
      } catch {
        copyBtn.textContent = '失败'
        setTimeout(() => {
          copyBtn.textContent = '复制'
        }, 1400)
      }
    })

    toolbar.appendChild(dots)
    toolbar.appendChild(lang)
    toolbar.appendChild(copyBtn)

    pre.parentNode.insertBefore(wrapper, pre)
    wrapper.appendChild(toolbar)
    wrapper.appendChild(pre)
  })
}

async function applyHighlight() {
  await nextTick()
  decorateCodeBlocks()
}

onMounted(async () => {
  const res = await axios.get(`${apiBase}/cards/${route.params.id}`)
  card.value = res.data
  applyHighlight()
})

</script>
