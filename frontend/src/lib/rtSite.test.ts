import { expect, it } from 'vitest'

import { buildRtQr, rtSiteLabel } from './rtSite'

it('mostra l\'URL del sito senza protocollo, www e barra finale', () => {
  expect(rtSiteLabel('https://atturk.github.io/rt/')).toBe('atturk.github.io/rt')
  expect(rtSiteLabel('http://www.rt.app')).toBe('rt.app')
})

it('il QR del sito ha tre occhi e il logo al centro', () => {
  const qr = buildRtQr('https://atturk.github.io/rt/')
  expect(qr.eyes).toHaveLength(3)
  expect(qr.path.length).toBeGreaterThan(0)
  expect(qr.logoAt * 2 + qr.logo).toBeCloseTo(qr.size)
  expect(qr.logo / qr.size).toBeLessThan(0.3)
})
