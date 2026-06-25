<script setup lang="ts">
/**
 * `<ArticleBody>` — renders pre-sanitised HTML and runs
 * `useEnhanceCodeBlocks` to give every fenced code block a toolbar +
 * copy button + highlight.js highlighting.
 *
 * The server (`services/markdown.py`) sanitises with `nh3` before the
 * HTML is persisted to `cards.body_html`, so trusting it via `v-html`
 * is the documented contract (phase2-architecture §3.7). No DOMPurify.
 */
import { ref } from 'vue'
import { useEnhanceCodeBlocks } from '../../../shared/composables/useEnhanceCodeBlocks'

defineProps<{
  /** Sanitised HTML; treated as trusted. */
  html: string
}>()

const root = ref<HTMLElement | null>(null)
useEnhanceCodeBlocks(root)
</script>

<template>
  <article
    ref="root"
    class="article-prose markdown-body"
    v-html="html"
  />
</template>
