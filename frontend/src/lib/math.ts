type Temml = typeof import('temml').default

/**
 * Delimitatori espliciti: $$…$$, \[…\], \(…\) e $…$. Per $…$ valgono le regole di Pandoc
 * (niente spazio dopo il $ di apertura e prima di quello di chiusura, niente cifra dopo),
 * così "costa 5$ e 10$" o "da $5 a $10" restano testo. Le stesse regole le applica l'API
 * (rt/core/markdown_render.py), che consegna le formule intatte in un solo nodo di testo.
 */
const DELIMITED = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<![\\$])\$(?=[^\s$])[^$\n]*?[^\s\\$]\$(?!\d))/g

function mathElement(temml: Temml, source: string, display: boolean, original: string): Node {
  const holder = window.document.createElement('span')
  // trust: false (predefinito) esclude \href, \class e simili; una formula non valida resta testo.
  // L'output è MathML generato da Temml, che fa l'escape del testo della formula.
  holder.innerHTML = temml.renderToString(source.trim(), { displayMode: display, throwOnError: false, annotate: true })
  const math = holder.querySelector('math')
  if (!math) return window.document.createTextNode(original) // formula non valida: resta il testo
  math.setAttribute('aria-label', source.trim())
  return math
}

function delimiters(token: string): [string, boolean] {
  if (token.startsWith('$$')) return [token.slice(2, -2), true]
  if (token.startsWith('\\[')) return [token.slice(2, -2), true]
  if (token.startsWith('\\(')) return [token.slice(2, -2), false]
  return [token.slice(1, -1), false]
}

/**
 * Riconosce solo delimitatori LaTeX espliciti nei nodi testuali e ignora code/pre.
 * Temml si carica solo se il documento contiene formule, fuori dal bundle principale.
 */
export async function renderDelimitedMath(root: HTMLElement): Promise<void> {
  const walker = window.document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const texts: Text[] = []
  for (let current = walker.nextNode() as Text | null; current; current = walker.nextNode() as Text | null) {
    if (current.parentElement?.closest('code,pre,script,style,math')) continue
    if (current.data.search(DELIMITED) >= 0) texts.push(current) // search ignora lastIndex, matchAll no
  }
  if (texts.length === 0) return
  const temml = (await import('temml')).default
  for (const text of texts) {
    if (!text.isConnected && !root.contains(text)) continue // il documento è cambiato nel frattempo
    const value = text.data
    const fragment = window.document.createDocumentFragment()
    let previous = 0
    for (const match of value.matchAll(DELIMITED)) {
      const index = match.index ?? 0
      fragment.append(value.slice(previous, index))
      const [source, display] = delimiters(match[0])
      fragment.append(mathElement(temml, source, display, match[0]))
      previous = index + match[0].length
    }
    fragment.append(value.slice(previous))
    text.replaceWith(fragment)
  }
}
