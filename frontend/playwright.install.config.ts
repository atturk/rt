import { defineConfig, devices } from '@playwright/test'

// Prova della web app installata dal comando di installazione (job CI 'installer', RT4-G2):
// niente server di test, si usa l'API già avviata dal servizio launchd.
export default defineConfig({
  testDir: './e2e-install',
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: 'list',
  use: {
    locale: 'it-IT',
    trace: 'retain-on-failure',
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
