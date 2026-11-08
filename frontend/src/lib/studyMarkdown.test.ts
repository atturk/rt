import { describe, expect, it } from 'vitest'
import { formatUnitAsMarkdown } from './studyMarkdown'

describe('formatUnitAsMarkdown', () => {
  it('include il titolo con ## e il Markdown pulito, togliendo immagini, allegati e commenti RT', () => {
    const raw = `<!-- rt-enrichment:start:123 -->
![Elemento grafico](assets/enrichment/diagramma.png)
[Apri la simulazione](assets/enrichment/sim.html)
<!-- rt-enrichment:end -->

Il **tessuto adiposo** è composto da adipociti e *trigliceridi*.

<img src="assets/images/foto.png">

Le formule fondamentali sono:
$E = mc^2$ e $$F = ma$$

- Punto 1
- Punto 2

[Allegato](assets/attachments/schema.pdf)`

    const result = formatUnitAsMarkdown({
      id: '4.2',
      title: 'Lipidi e trigliceridi',
      markdown: raw,
    })

    expect(result).toBe(`## 4.2 Lipidi e trigliceridi

Il **tessuto adiposo** è composto da adipociti e *trigliceridi*.

Le formule fondamentali sono:
$E = mc^2$ e $$F = ma$$

- Punto 1
- Punto 2`)
  })

  it('funziona anche con unità senza testo o senza id', () => {
    expect(formatUnitAsMarkdown({ id: '1.1', title: 'Introduzione', markdown: '' })).toBe('## 1.1 Introduzione')
    expect(formatUnitAsMarkdown({ title: 'Sola intestazione', markdown: null })).toBe('## Sola intestazione')
  })
})
