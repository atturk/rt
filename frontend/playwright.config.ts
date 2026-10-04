import { defineConfig, devices } from '@playwright/test'

// Test end-to-end della SPA contro l'API vera (niente mock di rete): scripts/e2e_server.py
// avvia 'rt api' + 'rt worker' su una cartella lezioni di prova e serve frontend/dist.
// Prima: npm run build. Tutti i test condividono lo stesso server, quindi girano in serie.
const PORT = Number(process.env.RT_E2E_PORT ?? 8766)
const PYTHON = process.env.RT_PYTHON ?? 'python3'

export default defineConfig({
  testDir: './e2e',
  // I test delle impostazioni cambiano il modello della rielaborazione e invalidano le
  // lezioni preparate. Recall e immagini partono con un server di prova indipendente.
  ...(process.env.RT_E2E_GROUP === 'recall-images'
    ? { testMatch: '**/recall-images-bot.spec.ts' }
    : process.env.RT_E2E_GROUP === 'other'
      ? { testIgnore: '**/recall-images-bot.spec.ts' }
      : {}),
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  // API vera su SQLite e YAML: alcune letture (elenco lezioni, impostazioni) richiedono qualche secondo.
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: 'it-IT',
    trace: 'retain-on-failure',
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // --telegram: gli e2e del bot finto lo vogliono acceso (dev.sh no: vale il predefinito, spento)
    command: `${PYTHON} ../scripts/e2e_server.py --port ${PORT} --telegram`,
    url: `http://127.0.0.1:${PORT}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 180_000,
    stdout: 'pipe',
  },
})
