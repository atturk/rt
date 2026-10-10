// Il server accetta solo nomi minuscoli (rt/api/routers/preferences.py): un nome diverso
// riceve 422 e usePreference rimette il valore precedente, come se il pulsante non funzionasse.
const SERVER_NAME = /^[a-z0-9][a-z0-9._-]{0,63}$/
const sources = import.meta.glob<string>(['/src/**/*.{ts,tsx}', '!/src/**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true })

it('ogni preferenza usata nello SPA ha un nome che il server accetta', () => {
  const names = Object.values(sources).flatMap(code => [...code.matchAll(/(?:usePreference|readPreference)(?:<[^>]*>)?\(\s*'([^']+)'/g)].map(m => m[1]))
  // Il raggruppamento per unità è sempre attivo; resta configurabile l'ordine.
  expect(names).toContain('review.order')
  expect(names.filter(name => !SERVER_NAME.test(name))).toEqual([])
})
