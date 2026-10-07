import { expect, it } from 'vitest'
import { rememberReturnAddress } from './returnAddress'

it('conserva percorso, query e hash attraverso Impostazioni, Bot e Job', () => {
  const address = rememberReturnAddress('/', { pathname: '/lezioni/15', search: '?panel=verifica', hash: '#unit-2.4' })
  expect(address).toBe('/lezioni/15?panel=verifica#unit-2.4')
  for (const pathname of ['/impostazioni', '/impostazioni/editor', '/bot', '/job', '/job/abc', '/importa']) {
    expect(rememberReturnAddress(address, { pathname, search: '', hash: '' })).toBe(address)
  }
  expect(rememberReturnAddress('/', { pathname: '/job', search: '', hash: '' })).toBe('/')
  expect(rememberReturnAddress(address, { pathname: '/studio/lezione/15', search: '', hash: '' })).toBe('/studio/lezione/15')
})
