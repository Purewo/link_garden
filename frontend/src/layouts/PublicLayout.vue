<template>
  <div class="lg-public">
    <header class="lg-public__nav">
      <div class="lg-public__nav-inner">
        <router-link to="/" class="lg-public__brand">Link Garden</router-link>
        <nav class="lg-public__links">
          <router-link to="/">首页</router-link>
          <router-link to="/admin">后台</router-link>
        </nav>
      </div>
    </header>
    <main class="lg-public__main">
      <slot />
    </main>
    <footer class="lg-public__footer">
      <p>是个人博客，也是技术收藏展厅。</p>
    </footer>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped>
.lg-public {
  min-height: 100vh;
  background: var(--color-bg, #060a16);
  color: var(--color-text, #d8e1ff);
  display: flex;
  flex-direction: column;
}
.lg-public__nav {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(6, 10, 22, 0.78);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.lg-public__nav-inner {
  max-width: 1180px;
  margin: 0 auto;
  padding: 0.7rem 1.2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.lg-public__brand {
  font-weight: 600;
  color: var(--color-text, #d8e1ff);
  text-decoration: none;
  letter-spacing: 0.04em;
}
.lg-public__links {
  display: flex;
  gap: 1.2rem;
}
.lg-public__links a {
  color: var(--color-text-muted, #8d99c1);
  text-decoration: none;
  font-size: 0.92rem;
  transition: color 0.18s ease;
}
.lg-public__links a:hover,
.lg-public__links a.router-link-active {
  color: var(--color-text, #d8e1ff);
}
.lg-public__main {
  flex: 1;
}
.lg-public__footer {
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  padding: 1.5rem 1.2rem;
  text-align: center;
  color: var(--color-text-muted, #8d99c1);
  font-size: 0.85rem;
}
</style>
