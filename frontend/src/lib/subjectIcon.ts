/**
 * Icone delle materie nella barra laterale ridotta: iniziali e colore, calcolati solo dal nome
 * (le materie non hanno un id: sono la stringa normalizzata in maiuscolo di info.yaml).
 * Modulo puro, senza React: il componente è components/SubjectIcon.tsx.
 */

/** Parole grammaticali italiane escluse dalle iniziali. Si estende con `extraStopwords`. */
export const SUBJECT_STOPWORDS: ReadonlySet<string> = new Set([
  // articoli (e forme elise: l', un')
  'il', 'lo', 'la', 'i', 'gli', 'le', 'l', 'un', 'uno', 'una',
  // preposizioni semplici (e d' eliso)
  'di', 'd', 'a', 'da', 'in', 'con', 'su', 'per', 'tra', 'fra',
  // preposizioni articolate
  'del', 'dello', 'della', 'dei', 'degli', 'delle', 'dell',
  'al', 'allo', 'alla', 'ai', 'agli', 'alle', 'all',
  'dal', 'dallo', 'dalla', 'dai', 'dagli', 'dalle', 'dall',
  'nel', 'nello', 'nella', 'nei', 'negli', 'nelle', 'nell',
  'col', 'coi', 'sul', 'sullo', 'sulla', 'sui', 'sugli', 'sulle', 'sull',
  // congiunzioni
  'e', 'ed', 'o', 'od', 'oppure',
])

export const MAX_INITIALS = 4

const ROMAN = /^(?=[ivx])x{0,3}(ix|iv|v?i{0,3})$/

/** Parole del nome: minuscole, apostrofi come separatori (dell'apparato → dell apparato). */
function words(name: string): string[] {
  return name
    .normalize('NFC')
    .toLocaleLowerCase('it')
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean)
}

/**
 * Iniziali delle prime quattro parole significative. Un numero resta intero (Patologia generale
 * 1 → P G 1) e così un numero romano in fondo al nome (Anatomia II → A II), anche se "i" è
 * anche un articolo. Se non resta nulla, la prima lettera o cifra del nome.
 */
export function subjectInitials(name: string, extraStopwords: Iterable<string> = []): string[] {
  const stop = new Set([...SUBJECT_STOPWORDS, ...[...extraStopwords].map((w) => w.toLocaleLowerCase('it'))])
  const all = words(name)
  const out: string[] = []
  all.forEach((word, index) => {
    if (out.length >= MAX_INITIALS) return
    if (/^\p{N}+$/u.test(word)) out.push(word.slice(0, 3))
    else if (index === all.length - 1 && index > 0 && ROMAN.test(word)) out.push(word.toUpperCase())
    else if (!stop.has(word)) out.push(word[0].toLocaleUpperCase('it'))
  })
  if (out.length > 0) return out
  const first = /[\p{L}\p{N}]/u.exec(name)
  return [first ? first[0].toLocaleUpperCase('it') : '?']
}

export type IconLayout = 'single' | 'row' | 'triangle' | 'grid'

/** 1 iniziale centrata; 2 affiancate; 3 = due sopra e una centrata sotto; 4 = griglia 2×2. */
export function iconLayout(count: number): IconLayout {
  if (count <= 1) return 'single'
  if (count === 2) return 'row'
  if (count === 3) return 'triangle'
  return 'grid'
}

/** Palette pastello (sfondo) con testo scuro: ogni coppia supera il contrasto AA (4,5:1). */
export const SUBJECT_PALETTE: readonly { bg: string; fg: string; name: string }[] = [
  { name: 'rosa', bg: '#fbd5dc', fg: '#1f1f1f' },
  { name: 'pesca', bg: '#fdd9bf', fg: '#1f1f1f' },
  { name: 'giallo', bg: '#fbeca0', fg: '#1f1f1f' },
  { name: 'lime', bg: '#dff0b8', fg: '#1f1f1f' },
  { name: 'verde', bg: '#bfe8cb', fg: '#1f1f1f' },
  { name: 'menta', bg: '#b9e6dc', fg: '#1f1f1f' },
  { name: 'turchese', bg: '#b5e3ef', fg: '#1f1f1f' },
  { name: 'cielo', bg: '#c3dcfa', fg: '#1f1f1f' },
  { name: 'pervinca', bg: '#d2d4fb', fg: '#1f1f1f' },
  { name: 'lavanda', bg: '#e1d1f7', fg: '#1f1f1f' },
  { name: 'orchidea', bg: '#f2cdef', fg: '#1f1f1f' },
  { name: 'salmone', bg: '#f7c9bf', fg: '#1f1f1f' },
  { name: 'sabbia', bg: '#eadcc4', fg: '#1f1f1f' },
  { name: 'salvia', bg: '#d3e2cf', fg: '#1f1f1f' },
  { name: 'ardesia', bg: '#d3dbe6', fg: '#1f1f1f' },
  { name: 'malva', bg: '#e8d3dc', fg: '#1f1f1f' },
]

/** Chiave della materia come nel backend: spazi ai lati tolti, maiuscolo. */
export function subjectKey(name: string): string {
  return name.trim().toLocaleUpperCase('it')
}

/** FNV-1a a 32 bit: stabile fra sessioni e browser. */
export function hashName(text: string): number {
  let h = 0x811c9dc5
  for (const ch of text) {
    h ^= ch.codePointAt(0) ?? 0
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h >>> 0
}

export type SubjectIconSpec = {
  name: string
  initials: string[]
  layout: IconLayout
  color: (typeof SUBJECT_PALETTE)[number]
}

/**
 * Icone di tutte le materie. Colore: ogni materia ha un colore preferito (hash del nome sulla
 * palette). Le collisioni si risolvono solo fra materie con le stesse iniziali: nel gruppo, in
 * ordine di (colore preferito, nome), ognuna prende il suo colore preferito se è libero,
 * altrimenti il successivo libero. Così il colore dipende solo dalle materie con le stesse
 * iniziali (aggiungerne una con iniziali diverse non cambia nulla) e materie con le stesse
 * iniziali hanno colori diversi finché sono al massimo quanti i colori della palette.
 */
export function subjectIcons(names: Iterable<string>, extraStopwords: Iterable<string> = []): Map<string, SubjectIconSpec> {
  const stop = [...extraStopwords]
  const groups = new Map<string, { name: string; initials: string[]; preferred: number }[]>()
  for (const raw of new Set([...names].map(subjectKey))) {
    const initials = subjectInitials(raw, stop)
    const key = initials.join(' ')
    const entry = { name: raw, initials, preferred: hashName(raw) % SUBJECT_PALETTE.length }
    groups.set(key, [...(groups.get(key) ?? []), entry])
  }
  const out = new Map<string, SubjectIconSpec>()
  for (const members of groups.values()) {
    members.sort((a, b) => a.preferred - b.preferred || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
    const taken = new Set<number>()
    for (const m of members) {
      let index = m.preferred
      for (let step = 0; step < SUBJECT_PALETTE.length && taken.has(index); step++) {
        index = (index + 1) % SUBJECT_PALETTE.length
      }
      taken.add(index)
      if (taken.size === SUBJECT_PALETTE.length) taken.clear() // più materie che colori: si ricomincia
      out.set(m.name, { name: m.name, initials: m.initials, layout: iconLayout(m.initials.length), color: SUBJECT_PALETTE[index] })
    }
  }
  return out
}

/** Rapporto di contrasto WCAG fra due colori #rrggbb. */
export function contrastRatio(a: string, b: string): number {
  const lum = (hex: string) => {
    const [r, g, bl] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl
  }
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
