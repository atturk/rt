import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

// RT4-FA9: l'interfaccia non cita comandi del terminale. Controlla il codice della SPA (senza
// commenti, test e client generato): una stringa visibile con "rt <comando>" o un'opzione
// della CLI fa fallire il test. I commenti per gli sviluppatori possono citare la CLI.

const SRC = join(__dirname, '..')
const COMMANDS =
  'run|build|web|api|worker|config|status|jobs|setup|recall|add-images|export|secrets|telegram-daemon|cost|review|outline|rewrite|prepare|validate-outline|validate-draft|storage|db|-u'
const TERMINAL = new RegExp(`\\brt (?:${COMMANDS})\\b|\\brt -u\\b|(?<![\\w-])--(?:mock|auto-accept|force|reset-token|web-search|units|channel|all|zip|legacy|concurrency)\\b`)

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return files(path)
    return /\.(tsx?|ts)$/.test(name) && !/\.test\.tsx?$/.test(name) && name !== 'schema.d.ts' ? [path] : []
  })
}

/** Toglie i commenti di riga e di blocco (anche quelli fra graffe nel JSX), lasciando il resto. */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')
}

describe('nessun riferimento al terminale nella SPA', () => {
  it('i testi visibili non citano comandi o opzioni di rt', () => {
    const found = files(SRC).flatMap((path) =>
      withoutComments(readFileSync(path, 'utf-8'))
        .split('\n')
        .map((line, i) => ({ line, i }))
        .filter(({ line }) => TERMINAL.test(line))
        .map(({ line, i }) => `${relative(SRC, path)}:${i + 1}: ${line.trim()}`),
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
