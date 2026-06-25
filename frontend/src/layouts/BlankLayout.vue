<template>
  <div class="lg-blank-layout">
    <slot />
  </div>
</template>

<script setup lang="ts"></script>

<style scoped>
.lg-blank-layout {
  min-height: 100vh;
  background: var(--color-bg, #060a16);
  color: var(--color-text, #d8e1ff);
  display: flex;
  flex-direction: column;
}
</style>
