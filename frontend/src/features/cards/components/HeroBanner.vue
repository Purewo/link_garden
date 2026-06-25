<script setup lang="ts">
/**
 * `<HeroBanner>` — homepage hero strip.
 *
 * Pure presentation: no external signed URL (PROJECT_NOTES 坑#5 — the
 * legacy code hardcoded a remote signed URL). Background lives in CSS
 * tokens (`assets/styles/home.css`); the component only carries copy.
 */
defineProps<{
  /** Primary headline. Defaults to the PROJECT_NOTES copy. */
  title?: string
  /** Secondary copy. */
  subtitle?: string
}>()
</script>

<template>
  <section class="hero-banner">
    <div class="hero-banner-inner">
      <h1 class="hero-banner-title">
        {{ title ?? 'Link Garden' }}
      </h1>
      <p class="hero-banner-subtitle">
        {{ subtitle ?? '是个人博客，也是技术收藏展厅' }}
      </p>
    </div>
  </section>
</template>
