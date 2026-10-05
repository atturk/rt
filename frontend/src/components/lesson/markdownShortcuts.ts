import { syntaxTree } from '@codemirror/language'
import { EditorSelection, type EditorState, type Extension, Prec } from '@codemirror/state'
import type { SyntaxNode } from '@lezer/common'
import { EditorView, keymap } from '@codemirror/view'

import { timecodeSpans } from './timecodeLock'

/**
 * Scorciatoie Markdown in stile Obsidian per l'editor delle lezioni:
 * - Mod-b: grassetto **
 * - Mod-i: corsivo *
 * - Mod-k: link [testo]() o [](url)
 * - Mod-Enter: spunta/despunta o aggiungi casella di spunta - [ ] / - [x]
 * - Mod-]: rientra righe
 * - Mod-[: riduce rientro righe
 * - Mod-d: elimina riga / paragrafo (sostituisce selectNextOccurrence di CodeMirror)
 * - Mod-Shift-x: barrato ~~
 * - Mod-Shift-c: codice inline `
 * - Mod-Shift-h: evidenziato ==
 *
 * Tutte le scorciatoie non hanno effetto dentro timecode bloccati, blocchi immagine, tabelle e se l'editor è in sola lettura.
 */

function isRangeBlocked(state: EditorState, from: number, to: number): boolean {
  if (state.readOnly) return true

  // Controllo timecode bloccati
  const spans = timecodeSpans(state)
  for (const span of spans) {
    if (from <= span.to && to >= span.from) return true
  }

  // Controllo linee per immagini, tabelle
  const startLine = state.doc.lineAt(from).number
  const endLine = state.doc.lineAt(to).number
  for (let n = startLine; n <= endLine; n++) {
    const line = state.doc.line(n)
    const trimmed = line.text.trim()
    if (/^!\[.*\]\(.*\)$/.test(trimmed)) return true
    if (/^\|.*\|$/.test(trimmed)) return true
  }

  // Controllo syntaxTree per tabelle
  const tree = syntaxTree(state)
  let node: { name: string; parent: any } | null = tree.resolveInner(from, 1)
  while (node) {
    if (['Table', 'TableRow', 'TableHeader', 'TableCell'].includes(node.name)) return true
    node = node.parent
  }

  return false
}

const isWordChar = (ch: string) => /[\p{L}\p{N}_]/u.test(ch)

function findWordAt(lineText: string, offset: number): { start: number; end: number } | null {
  let start = offset
  let end = offset
  if (offset > 0 && isWordChar(lineText[offset - 1])) {
    start = offset - 1
  } else if (offset < lineText.length && isWordChar(lineText[offset])) {
    end = offset + 1
  } else {
    return null
  }
  while (start > 0 && isWordChar(lineText[start - 1])) start--
  while (end < lineText.length && isWordChar(lineText[end])) end++
  return { start, end }
}

function isItalicDelim(delim: string): boolean {
  return delim === '*'
}

// Nodo del parser Markdown che corrisponde a ciascun delimitatore.
const WRAP_NODES: Record<string, string> = { '**': 'StrongEmphasis', '*': 'Emphasis', '~~': 'Strikethrough', '`': 'InlineCode', '==': 'Highlight' }

/** Il nodo (grassetto, corsivo…) che contiene tutta la selezione, anche se la selezione prende
 * solo una parte dei delimitatori (nell'anteprima in linea sono nascosti) o un cursore dentro
 * una frase di più parole. */
function enclosingWrap(state: EditorState, from: number, to: number, name: string) {
  for (const [pos, side] of [[from, 1], [to, -1]] as const) {
    for (let node: SyntaxNode | null = syntaxTree(state).resolveInner(pos, side); node; node = node.parent) {
      if (node.name === name && node.from <= from && node.to >= to) return node
    }
  }
  return null
}

/** Toglie i delimitatori di un nodo già presente; la selezione resta sul testo. */
function unwrapNode(view: EditorView, node: SyntaxNode): boolean {
  const open = node.firstChild
  const close = node.lastChild
  if (!open || !close || open === close || !open.name.endsWith('Mark') || !close.name.endsWith('Mark')) return false
  const changes = view.state.changes([{ from: open.from, to: open.to }, { from: close.from, to: close.to }])
  view.dispatch({ changes, selection: view.state.selection.map(changes), scrollIntoView: true })
  return true
}

function toggleWrap(view: EditorView, delim: string): boolean {
  const { state } = view
  let { main } = state.selection
  // bloccata: il tasto si consuma lo stesso (niente ricerca del browser con Mod-k, niente selectNextOccurrence con Mod-d)
  if (isRangeBlocked(state, main.from, main.to)) return true

  // Già formattato (secondo il parser, come Obsidian): si toglie la formattazione.
  const node = enclosingWrap(state, main.from, main.to, WRAP_NODES[delim])
  if (node && unwrapNode(view, node)) return true
  // Gli spazi ai bordi della selezione restano fuori dai delimitatori ("**testo** ", non "**testo **").
  if (!main.empty) {
    let from = main.from
    let to = main.to
    while (from < to && /\s/.test(state.sliceDoc(from, from + 1))) from++
    while (to > from && /\s/.test(state.sliceDoc(to - 1, to))) to--
    if (from < to && (from !== main.from || to !== main.to)) {
      main = EditorSelection.range(from, to)
    }
  }

  const dLen = delim.length

  if (!main.empty) {
    const from = main.from
    const to = main.to
    const selected = state.sliceDoc(from, to)

    // Verifica se è già avvolto internamente
    const isDoubleStarOnlyInside =
      isItalicDelim(delim) && selected.startsWith('**') && selected.endsWith('**') && !selected.startsWith('***')

    const isWrappedInside =
      selected.length >= 2 * dLen &&
      selected.startsWith(delim) &&
      selected.endsWith(delim) &&
      !isDoubleStarOnlyInside

    // Verifica se è già avvolto esternamente
    const before = state.sliceDoc(Math.max(0, from - dLen), from)
    const after = state.sliceDoc(to, Math.min(state.doc.length, to + dLen))

    const isDoubleStarOnlyOutside =
      isItalicDelim(delim) &&
      state.sliceDoc(Math.max(0, from - 2), from) === '**' &&
      state.sliceDoc(to, Math.min(state.doc.length, to + 2)) === '**'

    const isWrappedOutside = before === delim && after === delim && !isDoubleStarOnlyOutside

    if (isWrappedInside) {
      const unwrapped = selected.slice(dLen, -dLen)
      view.dispatch({
        changes: { from, to, insert: unwrapped },
        selection: { anchor: from, head: from + unwrapped.length },
        scrollIntoView: true,
      })
      return true
    }

    if (isWrappedOutside) {
      view.dispatch({
        changes: { from: from - dLen, to: to + dLen, insert: selected },
        selection: { anchor: from - dLen, head: to - dLen },
        scrollIntoView: true,
      })
      return true
    }

    // Altrimenti avvolgi la selezione
    view.dispatch({
      changes: { from, to, insert: `${delim}${selected}${delim}` },
      selection: { anchor: from + dLen, head: to + dLen },
      scrollIntoView: true,
    })
    return true
  }

  // Senza selezione: controlla se il cursore è dentro una parola
  const line = state.doc.lineAt(main.head)
  const offset = main.head - line.from
  const word = findWordAt(line.text, offset)

  if (word) {
    const wordStart = word.start
    const wordEnd = word.end
    const wordText = line.text.slice(wordStart, wordEnd)

    // Controlla se la parola è già avvolta
    const hasDelimBefore =
      wordStart >= dLen && line.text.slice(wordStart - dLen, wordStart) === delim
    const hasDelimAfter =
      wordEnd + dLen <= line.text.length && line.text.slice(wordEnd, wordEnd + dLen) === delim

    const isDoubleStarSurrounding =
      isItalicDelim(delim) &&
      wordStart >= 2 &&
      line.text.slice(wordStart - 2, wordStart) === '**' &&
      wordEnd + 2 <= line.text.length &&
      line.text.slice(wordEnd, wordEnd + 2) === '**'

    if (hasDelimBefore && hasDelimAfter && !isDoubleStarSurrounding) {
      // Togli i delimitatori attorno alla parola
      view.dispatch({
        changes: {
          from: line.from + wordStart - dLen,
          to: line.from + wordEnd + dLen,
          insert: wordText,
        },
        selection: { anchor: Math.max(line.from + wordStart, main.head - dLen) },
        scrollIntoView: true,
      })
      return true
    }

    // Avvolgi la parola
    view.dispatch({
      changes: {
        from: line.from + wordStart,
        to: line.from + wordEnd,
        insert: `${delim}${wordText}${delim}`,
      },
      selection: { anchor: main.head + dLen },
      scrollIntoView: true,
    })
    return true
  }

  // Nessuna parola: inserisci la coppia con il cursore in mezzo
  view.dispatch({
    changes: { from: main.head, insert: `${delim}${delim}` },
    selection: { anchor: main.head + dLen },
    scrollIntoView: true,
  })
  return true
}

export function toggleBold(view: EditorView): boolean {
  return toggleWrap(view, '**')
}

export function toggleItalic(view: EditorView): boolean {
  return toggleWrap(view, '*')
}

export function toggleStrikethrough(view: EditorView): boolean {
  return toggleWrap(view, '~~')
}

export function toggleInlineCode(view: EditorView): boolean {
  return toggleWrap(view, '`')
}

export function toggleHighlight(view: EditorView): boolean {
  return toggleWrap(view, '==')
}

export function toggleLink(view: EditorView): boolean {
  const { state } = view
  const { main } = state.selection
  // bloccata: il tasto si consuma lo stesso (niente ricerca del browser con Mod-k, niente selectNextOccurrence con Mod-d)
  if (isRangeBlocked(state, main.from, main.to)) return true

  if (main.empty) {
    view.dispatch({
      changes: { from: main.from, insert: '[]()' },
      selection: { anchor: main.from + 1 },
      scrollIntoView: true,
    })
    return true
  }

  const text = state.sliceDoc(main.from, main.to)
  const isUrl = /^(https?:\/\/|www\.)\S+$/i.test(text.trim())

  if (isUrl) {
    view.dispatch({
      changes: { from: main.from, to: main.to, insert: `[](${text})` },
      selection: { anchor: main.from + 1 },
      scrollIntoView: true,
    })
  } else {
    view.dispatch({
      changes: { from: main.from, to: main.to, insert: `[${text}]()` },
      selection: { anchor: main.from + text.length + 3 },
      scrollIntoView: true,
    })
  }
  return true
}

export function toggleCheckbox(view: EditorView): boolean {
  const { state } = view
  const { main } = state.selection
  // bloccata: il tasto si consuma lo stesso (niente ricerca del browser con Mod-k, niente selectNextOccurrence con Mod-d)
  if (isRangeBlocked(state, main.from, main.to)) return true

  const startLine = state.doc.lineAt(main.from).number
  const endLine = state.doc.lineAt(main.to).number
  const changes = []

  for (let n = startLine; n <= endLine; n++) {
    const line = state.doc.line(n)
    const text = line.text

    const checkedMatch = /^(\s*[-*+]\s+)\[[xX]\]\s*(.*)$/.exec(text)
    if (checkedMatch) {
      const newText = `${checkedMatch[1]}[ ] ${checkedMatch[2]}`
      changes.push({ from: line.from, to: line.to, insert: newText })
      continue
    }

    const uncheckedMatch = /^(\s*[-*+]\s+)\[ \]\s*(.*)$/.exec(text)
    if (uncheckedMatch) {
      const newText = `${uncheckedMatch[1]}[x] ${uncheckedMatch[2]}`
      changes.push({ from: line.from, to: line.to, insert: newText })
      continue
    }

    const listMatch = /^(\s*[-*+]\s+)(.*)$/.exec(text)
    if (listMatch) {
      const newText = `${listMatch[1]}[ ] ${listMatch[2]}`
      changes.push({ from: line.from, to: line.to, insert: newText })
      continue
    }

    const orderedMatch = /^(\s*\d+[.)]\s+)(.*)$/.exec(text)
    if (orderedMatch) {
      const newText = `${orderedMatch[1]}[ ] ${orderedMatch[2]}`
      changes.push({ from: line.from, to: line.to, insert: newText })
      continue
    }

    const indentMatch = /^(\s*)(.*)$/.exec(text)
    if (indentMatch) {
      const newText = `${indentMatch[1]}- [ ] ${indentMatch[2]}`
      changes.push({ from: line.from, to: line.to, insert: newText })
    }
  }

  if (changes.length === 0) return false
  view.dispatch({ changes, scrollIntoView: true })
  return true
}

export function indentMoreLines(view: EditorView): boolean {
  const { state } = view
  const { main } = state.selection
  // bloccata: il tasto si consuma lo stesso (niente ricerca del browser con Mod-k, niente selectNextOccurrence con Mod-d)
  if (isRangeBlocked(state, main.from, main.to)) return true

  const startLine = state.doc.lineAt(main.from).number
  const endLine = state.doc.lineAt(main.to).number
  const changes = []

  for (let n = startLine; n <= endLine; n++) {
    const line = state.doc.line(n)
    changes.push({ from: line.from, insert: '  ' })
  }

  view.dispatch({ changes, scrollIntoView: true })
  return true
}

export function indentLessLines(view: EditorView): boolean {
  const { state } = view
  const { main } = state.selection
  // bloccata: il tasto si consuma lo stesso (niente ricerca del browser con Mod-k, niente selectNextOccurrence con Mod-d)
  if (isRangeBlocked(state, main.from, main.to)) return true

  const startLine = state.doc.lineAt(main.from).number
  const endLine = state.doc.lineAt(main.to).number
  const changes = []

  for (let n = startLine; n <= endLine; n++) {
    const line = state.doc.line(n)
    if (line.text.startsWith('  ')) {
      changes.push({ from: line.from, to: line.from + 2 })
    } else if (line.text.startsWith('\t') || line.text.startsWith(' ')) {
      changes.push({ from: line.from, to: line.from + 1 })
    }
  }

  if (changes.length === 0) return false
  view.dispatch({ changes, scrollIntoView: true })
  return true
}

export function deleteLineOrParagraph(view: EditorView): boolean {
  const { state } = view
  const { main } = state.selection
  // bloccata: il tasto si consuma lo stesso (niente ricerca del browser con Mod-k, niente selectNextOccurrence con Mod-d)
  if (isRangeBlocked(state, main.from, main.to)) return true

  const startLine = state.doc.lineAt(main.from)
  const endLine = state.doc.lineAt(main.to)

  let from = startLine.from
  let to = endLine.to

  if (to < state.doc.length) {
    to += 1
  } else if (from > 0) {
    from -= 1
  }

  view.dispatch({
    changes: { from, to },
    scrollIntoView: true,
  })
  return true
}

export const markdownShortcuts: Extension = Prec.high(
  keymap.of([
    { key: 'Mod-b', run: toggleBold },
    { key: 'Mod-i', run: toggleItalic },
    { key: 'Mod-k', run: toggleLink },
    { key: 'Mod-Enter', run: toggleCheckbox },
    { key: 'Mod-]', run: indentMoreLines },
    { key: 'Mod-[', run: indentLessLines },
    { key: 'Mod-d', run: deleteLineOrParagraph },
    { key: 'Mod-Shift-x', run: toggleStrikethrough },
    { key: 'Mod-Shift-c', run: toggleInlineCode },
    { key: 'Mod-Shift-h', run: toggleHighlight },
  ]),
)
