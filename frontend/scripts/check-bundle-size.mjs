#!/usr/bin/env node
// Budget del JavaScript iniziale della web app (dopo 'npm run build').
// Misura il chunk d'ingresso di dist/index.html più i chunk che importa staticamente (i
// <link rel="modulepreload">): è quello che il browser scarica prima di mostrare una pagina.
// Le pagine delle aree sono chunk a parte (routes/index.tsx) e qui non contano.
// Esce con 1 se si supera il budget. Budget = misura di 4.2.0b1 + ~10% di margine: se cresce
// per un buon motivo si alza qui, nello stesso commit.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const BUDGET = { raw: 490_000, gzip: 156_000 }

const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist')
let html
try {
  html = readFileSync(join(dist, 'index.html'), 'utf8')
} catch {
  console.error('dist/index.html non trovato: prima npm run build')
  process.exit(1)
}

const entry = html.match(/<script type="module"[^>]*\ssrc="\/([^"]+\.js)"/)?.[1]
if (!entry) {
  console.error('Chunk d\'ingresso non trovato in dist/index.html')
  process.exit(1)
}
const preloads = [...html.matchAll(/<link rel="modulepreload"[^>]*\shref="\/([^"]+\.js)"/g)].map((m) => m[1])

const kb = (n) => `${(n / 1000).toFixed(2)} kB`
const total = { raw: 0, gzip: 0 }
for (const file of [entry, ...preloads]) {
  const bytes = readFileSync(join(dist, file))
  const size = { raw: bytes.length, gzip: gzipSync(bytes).length }
  total.raw += size.raw
  total.gzip += size.gzip
  console.log(`${file === entry ? 'ingresso' : 'statico '}  ${file.padEnd(40)} ${kb(size.raw).padStart(10)}  gzip ${kb(size.gzip).padStart(9)}`)
}
console.log(`totale    ${''.padEnd(40)} ${kb(total.raw).padStart(10)}  gzip ${kb(total.gzip).padStart(9)}`)
console.log(`budget    ${''.padEnd(40)} ${kb(BUDGET.raw).padStart(10)}  gzip ${kb(BUDGET.gzip).padStart(9)}`)

const over = ['raw', 'gzip'].filter((k) => total[k] > BUDGET[k])
if (over.length) {
  console.error(`JavaScript iniziale oltre il budget (${over.join(', ')}): carica a parte quello che non serve subito.`)
  process.exit(1)
}
