import type { LessonImage } from '@/api/images'

export type MediaGroup = {
  name: string
  images: LessonImage[]
  usedCount: number
  totalCount: number
  flatStartIndex: number
}

export function groupMediaImages(images: LessonImage[]): MediaGroup[] {
  const map = new Map<string, LessonImage[]>()
  for (const img of images) {
    const key =
      img.source_name ||
      (img.source === 'web'
        ? 'Dal web'
        : img.source === 'editor' || img.source === 'upload'
          ? "Dall'editor"
          : img.source === 'enrichment'
            ? 'Arricchimento'
            : 'Altre immagini')
    if (!map.has(key)) {
      map.set(key, [])
    }
    map.get(key)!.push(img)
  }

  const groups: MediaGroup[] = []
  let runningIndex = 0
  for (const [name, imgs] of map.entries()) {
    const usedCount = imgs.filter((i) => i.in_document).length
    groups.push({
      name,
      images: imgs,
      usedCount,
      totalCount: imgs.length,
      flatStartIndex: runningIndex,
    })
    runningIndex += imgs.length
  }
  return groups
}

export function flashAndScroll(el: HTMLElement | Element) {
  const htmlEl = el as HTMLElement
  let container: HTMLElement | null = htmlEl.closest<HTMLElement>('.rt-panel-container')
  if (!container) {
    let parent = htmlEl.parentElement
    while (parent && parent !== document.body && parent !== document.documentElement) {
      const style = window.getComputedStyle(parent)
      if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
        container = parent
        break
      }
      parent = parent.parentElement
    }
  }

  if (container) {
    const containerRect = container.getBoundingClientRect()
    const elRect = htmlEl.getBoundingClientRect()
    const offset = (elRect.top + elRect.height / 2) - (containerRect.top + containerRect.height / 2)
    const target = Math.max(0, container.scrollTop + offset)
    if (typeof container.scrollTo === 'function') {
      container.scrollTo({ top: target, behavior: 'smooth' })
    } else {
      container.scrollTop = target
    }
  } else if (typeof htmlEl.scrollIntoView === 'function') {
    htmlEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  htmlEl.classList.add('rt-media-flash')
  const btn = htmlEl.querySelector('button')
  btn?.classList.add('rt-media-flash')
  const onEnd = () => {
    htmlEl.classList.remove('rt-media-flash')
    btn?.classList.remove('rt-media-flash')
    htmlEl.removeEventListener('animationend', onEnd)
    btn?.removeEventListener('animationend', onEnd)
  }
  htmlEl.addEventListener('animationend', onEnd)
  btn?.addEventListener('animationend', onEnd)
}
