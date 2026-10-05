import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  base: '/app/',
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        name: 'HRAgents',
        short_name: 'HRAgents',
        description: 'A virtual HR team for the HR department of one.',
        theme_color: '#ffffff',
        background_color: '#ffffff',
        display: 'standalone',
        scope: '/app/',
        start_url: '/app/',
        lang: 'en',
        icons: [
          {
            src: 'pwa-192x192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png',
          },
          {
            src: 'pwa-maskable-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // Static shell only: HR data is never cached, every read hits the API.
        navigateFallback: '/app/index.html',
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/v1': 'http://localhost:8000',
      '/healthz': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Radix/dnd interaction tests flake under parallel CPU load at the 5s default.
    // 30s, not 15s: on a contended 8-core box `ImportPage.test.tsx` took 42s for
    // three tests that run in 13s on an idle machine. A timeout that fires on CPU
    // contention is a flaky gate, not a signal.
    testTimeout: 30000,
    // Bound the worker pool: one fork per core exhausts memory on an 8 GB
    // machine (and in CI containers), which surfaces as "Failed to start forks
    // worker" or 15s timeouts rather than as a real test failure.
    maxWorkers: 3,
    fileParallelism: true,
    // One jsdom environment per test file cost 107s of a 76s wall clock and was
    // the reason a CI run once finished only 21 of 33 files before exhausting
    // memory. `vmThreads` still gives each file its own globals -- which the
    // tests rely on, since they mutate module-level state such as the i18n
    // language -- but reuses the realm.
    pool: 'vmThreads',
  },
})
