// RT4-FA9: l'interfaccia non cita comandi del terminale. Controlla il codice della SPA (senza
// commenti, test e client generato): una stringa visibile con "rt <comando>" o un'opzione
// della CLI fa fallire il test. I commenti per gli sviluppatori possono citare la CLI.

// Tutti i sorgenti della SPA come testo (Vite), senza test e client generato.
const SOURCES = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!../api/schema.d.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>
const COMMANDS =
  'run|build|web|api|worker|config|status|jobs|setup|recall|add-images|export|secrets|telegram-daemon|cost|review|outline|rewrite|prepare|validate-outline|validate-draft|storage|db|-u'
const TERMINAL = new RegExp(`\\brt (?:${COMMANDS})\\b|\\brt -u\\b|(?<![\\w-])--(?:mock|auto-accept|force|reset-token|web-search|units|channel|all|zip|legacy|concurrency)\\b`)

/** Toglie i commenti di riga e di blocco (anche quelli fra graffe nel JSX), lasciando il resto. */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')
}

describe('nessun riferimento al terminale nella SPA', () => {
  it('i testi visibili non citano comandi o opzioni di rt', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(20)
    const found = Object.entries(SOURCES).flatMap(([path, source]) =>
      withoutComments(source)
        .split('\n')
        .map((line, i) => ({ line, i }))
        .filter(({ line }) => TERMINAL.test(line))
        .map(({ line, i }) => `${path}:${i + 1}: ${line.trim()}`),
    )
    expect(found).toEqual([])
  })

  it('il controllo riconosce i riferimenti', () => {
    expect(TERMINAL.test("Come 'rt run --mock'.")).toBe(true)
    expect(TERMINAL.test('Esegui prima rt build')).toBe(true)
    expect(TERMINAL.test('Alert tone="danger"')).toBe(false)
    expect(TERMINAL.test('var(--wave-played)')).toBe(false)
  })
})
