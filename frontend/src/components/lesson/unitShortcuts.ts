import { mountDomTooltip } from '@/components/ui/dom-tooltip'

const ICONS = {
  study: ['M12 7v14', 'M3 18V3a1 1 0 0 1 1-1h3a5 5 0 0 1 5 5 5 5 0 0 1 5-5h3a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1h-3a5 5 0 0 0-5 2 5 5 0 0 0-5-2H4a1 1 0 0 1-1-1Z'],
  recall: ['m3 6 2 2 4-4', 'M13 6h8', 'm3 13 2 2 4-4', 'M13 13h8', 'M5 20h.01', 'M13 20h8'],
  // Copy di Lucide con una K nel foglio davanti.
  keywords: ['M10 8h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2Z', 'M4 16a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2', 'M12 10.5v9', 'M18.5 10.5 12 15.5', 'M14.4 13.7l4.1 5.8'],
  copied: ['M20 6 9 17l-5-5'],
}

/** Percorsi delle icone Lucide, senza montare altre radici React. */
function shortcutIcon(kind: keyof typeof ICONS) {
  const svg = window.document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  for (const [name, value] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.7', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) svg.setAttribute(name, value)
  for (const d of ICONS[kind]) {
    const path = window.document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', d)
    svg.append(path)
  }
  return svg
}

/** Link veri, condivisi dalla lettura HTML e dai widget dell'editor. */
export function createUnitShortcuts(lessonId: number, unitId: string, navigate: (href: string) => void, keywords: string[] = []) {
  const shortcuts = document.createElement('span')
  shortcuts.className = 'rt-unit-shortcuts'
  for (const recall of [false, true]) {
    const link = document.createElement('a')
    const href = `/studio/lezione/${lessonId}?unita=${encodeURIComponent(unitId)}${recall ? '&azione=ripasso' : ''}`
    link.href = href
    link.setAttribute('aria-label', `${recall ? 'Ripassa' : 'Studia'} l'unità ${unitId}`)
    link.append(shortcutIcon(recall ? 'recall' : 'study'))
    mountDomTooltip(link, recall ? 'Mettimi alla prova su questa unità' : 'Studia questa unità')
    link.addEventListener('click', event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.defaultPrevented) return
      event.preventDefault()
      navigate(href)
    })
    shortcuts.append(link)
  }
  if (keywords.length) shortcuts.append(keywordsButton(unitId, keywords))
  return shortcuts
}

/** Copia le keywords della scaletta, una per riga (una keyword può contenere virgole). */
function keywordsButton(unitId: string, keywords: string[]) {
  const button = document.createElement('button')
  button.type = 'button'
  button.setAttribute('aria-label', `Copia le keywords dell'unità ${unitId}`)
  button.append(shortcutIcon('keywords'))
  mountDomTooltip(button, 'Copia le keywords')
  let timer: number | undefined
  button.addEventListener('click', event => {
    event.preventDefault()
    event.stopPropagation()
    const text = keywords.join('\n')
    void navigator.clipboard.writeText(text).then(() => {
      button.replaceChildren(shortcutIcon('copied'))
      window.clearTimeout(timer)
      timer = window.setTimeout(() => button.replaceChildren(shortcutIcon('keywords')), 1200)
    }).catch(() => undefined)
  })
  return button
}
