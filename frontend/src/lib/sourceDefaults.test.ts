import { expect, it } from 'vitest'

import { SOURCE_DEFAULTS, defaultOptions } from './sourceDefaults'

it('Word, TXT e MD restano solo testo e tengono l’uso scelto anche se i Documenti sono su Solo immagini', () => {
  const defaults = { ...SOURCE_DEFAULTS, testo: { estrai: 'solo_immagini' as const, uso: 'integra' as const } }
  expect(defaultOptions('appunti.docx', defaults)).toEqual({ estrai: 'testo', uso: 'integra', pagine: null })
  expect(defaultOptions('dispensa.pdf', defaults, 'testo')).toEqual({ estrai: 'solo_immagini', uso: 'contesto', pagine: null })
})
