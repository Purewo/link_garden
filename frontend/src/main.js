import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import HomeView from './views/HomeView.vue'
import DetailView from './views/DetailView.vue'
import AdminView from './views/AdminView.vue'
import AdminPublishView from './views/AdminPublishView.vue'
import './assets/style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/card/:id', component: DetailView, props: true },
    { path: '/admin', component: AdminView },
    { path: '/admin/publish', component: AdminPublishView },
  ],
})

createApp(App).use(router).mount('#app')
