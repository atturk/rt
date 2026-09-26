import { defineConfig, devices } from '@playwright/test'

// Test end-to-end della SPA contro l'API vera (niente mock di rete): scripts/e2e_server.py
// avvia 'rt api' + 'rt worker' su una cartella lezioni di prova e serve frontend/dist.
// Prima: npm run build. Tutti i test condividono lo stesso server, quindi girano in serie.
const PORT = Number(process.env.RT_E2E_PORT ?? 8766)
const PYTHON = process.env.RT_PYTHON ?? 'python3'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: 'it-IT',
    trace: 'retain-on-failure',
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `${PYTHON} ../scripts/e2e_server.py --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 180_000,
    stdout: 'pipe',
  },
})
