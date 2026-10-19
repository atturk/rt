import { mountDomTooltip } from '@/components/ui/dom-tooltip'

/** Percorsi delle icone Lucide BookOpen e ListChecks, senza montare altre radici React. */
function shortcutIcon(recall: boolean) {
  const svg = window.document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  for (const [name, value] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.7', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) svg.setAttribute(name, value)
  const paths = recall
    ? ['m3 6 2 2 4-4', 'M13 6h8', 'm3 13 2 2 4-4', 'M13 13h8', 'M5 20h.01', 'M13 20h8']
    : ['M12 7v14', 'M3 18V3a1 1 0 0 1 1-1h3a5 5 0 0 1 5 5 5 5 0 0 1 5-5h3a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1h-3a5 5 0 0 0-5 2 5 5 0 0 0-5-2H4a1 1 0 0 1-1-1Z']
  for (const d of paths) {
    const path = window.document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', d)
    svg.append(path)
  }
  return svg
}

/** Link veri, condivisi dalla lettura HTML e dai widget dell'editor. */
export function createUnitShortcuts(lessonId: number, unitId: string, navigate: (href: string) => void) {
  const shortcuts = document.createElement('span')
  shortcuts.className = 'rt-unit-shortcuts'
  for (const recall of [false, true]) {
    const link = document.createElement('a')
    const href = `/studio/lezione/${lessonId}?unita=${encodeURIComponent(unitId)}${recall ? '&azione=ripasso' : ''}`
    link.href = href
    link.setAttribute('aria-label', `${recall ? 'Ripassa' : 'Studia'} l'unità ${unitId}`)
    link.append(shortcutIcon(recall))
    mountDomTooltip(link, recall ? 'Mettimi alla prova su questa unità' : 'Studia questa unità')
    link.addEventListener('click', event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.defaultPrevented) return
      event.preventDefault()
      navigate(href)
    })
    shortcuts.append(link)
  }
  return shortcuts
}
