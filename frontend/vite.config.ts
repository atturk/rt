/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In sviluppo 'npm run dev' inoltra /api e /login a 'rt api' (127.0.0.1:8765): stessa
// origine come in produzione, dove FastAPI serve la build.
const API = process.env.RT_API_URL ?? 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    proxy: {
      '/api': { target: API, changeOrigin: false },
      '/login': {
        target: API,
        // Solo il link monouso va all'API; /login senza codice è la pagina della SPA.
        bypass: (req) => (req.url?.includes('code=') ? undefined : req.url),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    globals: true,
  },
})
