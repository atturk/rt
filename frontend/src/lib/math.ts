const NS = 'http://www.w3.org/1998/Math/MathML'
const COMMANDS: Record<string, [string, string]> = {
  alpha: ['mi', 'α'], beta: ['mi', 'β'], gamma: ['mi', 'γ'], delta: ['mi', 'δ'], epsilon: ['mi', 'ε'],
  theta: ['mi', 'θ'], lambda: ['mi', 'λ'], mu: ['mi', 'μ'], pi: ['mi', 'π'], sigma: ['mi', 'σ'],
  phi: ['mi', 'φ'], omega: ['mi', 'ω'], Gamma: ['mi', 'Γ'], Delta: ['mi', 'Δ'], Sigma: ['mi', 'Σ'], Omega: ['mi', 'Ω'],
  times: ['mo', '×'], cdot: ['mo', '·'], pm: ['mo', '±'], le: ['mo', '≤'], leq: ['mo', '≤'], ge: ['mo', '≥'], geq: ['mo', '≥'],
  neq: ['mo', '≠'], ne: ['mo', '≠'], approx: ['mo', '≈'], infty: ['mo', '∞'], to: ['mo', '→'], rightarrow: ['mo', '→'],
  leftarrow: ['mo', '←'], degree: ['mo', '°'], percent: ['mo', '%'], sum: ['mo', '∑'], prod: ['mo', '∏'], int: ['mo', '∫'],
}

function node(tag: string, text?: string) {
  const el = window.document.createElementNS(NS, tag)
  if (text != null) el.textContent = text
  return el
}

const TOKEN = /\\[a-zA-Z]+|\\.|\d+(?:[.,]\d+)?|[a-zA-Z]+|[{}_^]|[+\-=<>()[\],|/]|./gs

/** Parser volutamente circoscritto: gruppi, indici, potenze, frazioni, radici e simboli comuni. */
function mathRow(source: string): Element {
  const tokens = source.match(TOKEN) ?? []
  let at = 0
  function atom(): Element {
    const token = tokens[at++] ?? ''
    if (token === '{') return sequence(true)
    if (token.startsWith('\\')) {
      const name = token.slice(1)
      if ([",", ";", "!", ":", "quad", "qquad"].includes(name)) return node('mspace')
      if (name === "%") return node('mo', '%')
      if (name === "left" || name === "right") return atom()
      if (name === 'frac' || name === 'dfrac' || name === 'tfrac') {
        const fraction = node('mfrac')
        fraction.append(atom(), atom())
        return fraction
      }
      if (name === 'sqrt') {
        const root = node('msqrt')
        root.append(atom())
        return root
      }
      if (name === 'text' || name === 'mathrm' || name === 'mathbf') {
        const value = tokens[at] === '{' ? atom().textContent ?? '' : tokens[at++] ?? ''
        return node(name === 'text' ? 'mtext' : 'mi', value)
      }
      const [tag, value] = COMMANDS[name] ?? ['mi', name || token.slice(1)]
      return node(tag, value)
    }
    if (token === ' ') return node('mspace')
    if (/^\d/.test(token)) return node('mn', token)
    if (/^[a-zA-Z]+$/.test(token)) return node(token.length === 1 ? 'mi' : 'mtext', token)
    return node('mo', token)
  }
  function sequence(group = false): Element {
    const row = node('mrow')
    while (at < tokens.length) {
      if (tokens[at] === '}' && group) { at++; break }
      const script = tokens[at]
      if ((script === '^' || script === '_') && row.lastElementChild) {
        at++
        const base = row.lastElementChild
        row.removeChild(base)
        const wrapped = node(script === '^' ? 'msup' : 'msub')
        wrapped.append(base, atom())
        row.append(wrapped)
      } else if (script === '^' || script === '_') {
        at++ // ignora indici senza base
        atom()
      } else row.append(atom())
    }
    return row
  }
  return sequence()
}

const DELIMITED = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\\)\$[^$\n]+?\$)/g

function mathElement(source: string, display: boolean) {
  const math = node('math')
  math.setAttribute('display', display ? 'block' : 'inline')
  math.setAttribute('aria-label', source.trim())
  math.append(mathRow(source.trim()))
  return math
}

/** Riconosce solo delimitatori LaTeX espliciti nei nodi testuali e ignora code/pre. */
export function renderDelimitedMath(root: HTMLElement): void {
  const walker = window.document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const texts: Text[] = []
  for (let current = walker.nextNode() as Text | null; current; current = walker.nextNode() as Text | null) {
    if (current.parentElement?.closest('code,pre,script,style,math')) continue
    if (DELIMITED.test(current.data)) { texts.push(current); DELIMITED.lastIndex = 0 }
  }
  for (const text of texts) {
    const value = text.data
    const fragment = window.document.createDocumentFragment()
    let previous = 0
    DELIMITED.lastIndex = 0
    for (const match of value.matchAll(DELIMITED)) {
      const index = match.index ?? 0
      fragment.append(value.slice(previous, index))
      const token = match[0]
      const display = token.startsWith('$$') || token.startsWith('\\[')
      const source = token.startsWith('$$') ? token.slice(2, -2) : token.startsWith('\\[') ? token.slice(2, -2) : token.startsWith('\\(') ? token.slice(2, -2) : token.slice(1, -1)
      fragment.append(mathElement(source, display))
      previous = index + token.length
    }
    fragment.append(value.slice(previous))
    text.replaceWith(fragment)
  }
}
