<template>
  <section class="lg-404">
    <div class="lg-404__inner">
      <h1>404</h1>
      <p>找不到这片花田。链接可能已被归档，或从未存在。</p>
      <router-link to="/" class="lg-404__home">回到首页</router-link>
    </div>
  </section>
</template>

<script setup lang="ts"></script>

<style scoped>
.lg-404 {
  min-height: 60vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4rem 1.2rem;
}
.lg-404__inner {
  text-align: center;
  color: var(--color-text, #d8e1ff);
  max-width: 480px;
}
.lg-404__inner h1 {
  font-size: 5rem;
  margin: 0;
  color: var(--color-accent, #00aaff);
  letter-spacing: 0.05em;
}
.lg-404__inner p {
  color: var(--color-text-muted, #8d99c1);
  margin: 0.8rem 0 1.5rem;
}
.lg-404__home {
  display: inline-block;
  padding: 0.6rem 1.4rem;
  border-radius: 999px;
  background: rgba(0, 170, 255, 0.16);
  color: var(--color-accent, #00aaff);
  border: 1px solid rgba(0, 170, 255, 0.45);
  text-decoration: none;
  transition: background 0.18s ease;
}
.lg-404__home:hover {
  background: rgba(0, 170, 255, 0.28);
}
</style>
