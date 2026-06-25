/**
 * Frontend entrypoint.
 *
 * Wires up Pinia (+ persistedstate plugin), Vue Router, and global CSS.
 * Feature stores hook themselves up lazily on first access.
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'

import App from './App.vue'
import { router } from './router'

import './assets/styles/tokens.css'
import './assets/styles/reset.css'
import './assets/styles/global.css'
import './assets/styles/hljs-theme.css'
import './assets/styles/article.css'
import './assets/styles/home.css'
import './assets/styles/admin.css'

const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

const app = createApp(App)
app.use(pinia)
app.use(router)

app.mount('#app')
