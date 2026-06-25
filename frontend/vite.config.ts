import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import checker from 'vite-plugin-checker'
import { fileURLToPath, URL } from 'node:url'

// Frontend dev hits the FastAPI backend through a proxy so cookies, JWT, and
// relative URLs behave the same as production (nginx -> 127.0.0.1:5001).
export default defineConfig(({ command }) => {
  const isBuild = command === 'build'
  return {
    plugins: [
      vue(),
      // The checker plugin only runs in dev (it's redundant in CI build, where
      // `pnpm typecheck` and `pnpm lint` are run as separate gates).
      ...(isBuild
        ? []
        : [
            checker({
              vueTsc: true,
              eslint: {
                useFlatConfig: true,
                lintCommand: 'eslint .',
              },
            }),
          ]),
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 5173,
      strictPort: false,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:5001',
          changeOrigin: true,
        },
        '/covers': {
          target: 'http://127.0.0.1:5001',
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      target: 'es2022',
      rollupOptions: {
        output: {
          manualChunks: (id) => {
            if (id.includes('node_modules/highlight.js')) return 'hljs'
            if (id.includes('node_modules/md-editor-v3')) return 'md-editor'
            if (id.includes('node_modules/vue') || id.includes('node_modules/pinia')) {
              return 'vue-vendor'
            }
            return undefined
          },
        },
      },
    },
  }
})
