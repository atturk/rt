let activeCleanupFn: (() => void) | null = null
let transparentImg: HTMLImageElement | null = null

function getTransparentDragImage(): HTMLImageElement {
  if (!transparentImg && typeof Image !== 'undefined') {
    transparentImg = new Image()
    transparentImg.src =
      'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
  }
  return transparentImg as HTMLImageElement
}

export interface DragPreviewOptions {
  urls: string[]
  count?: number
}

export function createDragPreviewDOM(options: DragPreviewOptions): HTMLElement {
  const count = options.count ?? options.urls.length
  const primaryUrl = options.urls[0] || ''

  const wrapper = document.createElement('div')
  wrapper.className = 'rt-drag-preview'
  wrapper.style.position = 'fixed'
  wrapper.style.pointerEvents = 'none'
  wrapper.style.zIndex = '99999'
  wrapper.style.transform = 'translate3d(0, 0, 0)'
  wrapper.style.width = '68px'

  if (count > 1) {
    // A mazzo: 2 o 3 miniature sfalsate con badge
    wrapper.style.height = '52px'

    // Card di sfondo 2 (se almeno 3)
    if (count >= 3) {
      const cardBack2 = document.createElement('div')
      cardBack2.className = 'rt-drag-preview-stack rt-drag-preview-stack-2'
      cardBack2.style.position = 'absolute'
      cardBack2.style.inset = '0'
      cardBack2.style.borderRadius = '8px'
      cardBack2.style.border = '1px solid rgba(0, 0, 0, 0.15)'
      cardBack2.style.background = '#e2e8f0'
      cardBack2.style.transform = 'rotate(-6deg) scale(0.94)'
      cardBack2.style.boxShadow = '0 2px 6px rgba(0, 0, 0, 0.12)'
      wrapper.appendChild(cardBack2)
    }

    // Card di sfondo 1
    const cardBack1 = document.createElement('div')
    cardBack1.className = 'rt-drag-preview-stack rt-drag-preview-stack-1'
    cardBack1.style.position = 'absolute'
    cardBack1.style.inset = '0'
    cardBack1.style.borderRadius = '8px'
    cardBack1.style.border = '1px solid rgba(0, 0, 0, 0.15)'
    cardBack1.style.background = '#cbd5e1'
    cardBack1.style.transform = 'rotate(4deg) scale(0.97)'
    cardBack1.style.boxShadow = '0 3px 8px rgba(0, 0, 0, 0.14)'
    wrapper.appendChild(cardBack1)

    // Card principale
    const cardMain = document.createElement('div')
    cardMain.className = 'rt-drag-preview-main'
    cardMain.style.position = 'relative'
    cardMain.style.width = '68px'
    cardMain.style.height = '50px'
    cardMain.style.borderRadius = '8px'
    cardMain.style.border = '1px solid rgba(0, 0, 0, 0.15)'
    cardMain.style.overflow = 'hidden'
    cardMain.style.background = '#ffffff'
    cardMain.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.16)'

    const img = document.createElement('img')
    img.src = primaryUrl
    img.alt = ''
    img.style.width = '100%'
    img.style.height = '100%'
    img.style.objectFit = 'cover'
    img.style.display = 'block'
    cardMain.appendChild(img)
    wrapper.appendChild(cardMain)

    // Badge con il numero
    const badge = document.createElement('span')
    badge.className = 'rt-drag-preview-badge'
    badge.textContent = String(count)
    badge.style.position = 'absolute'
    badge.style.top = '-6px'
    badge.style.right = '-6px'
    badge.style.minWidth = '20px'
    badge.style.height = '20px'
    badge.style.padding = '0 5px'
    badge.style.borderRadius = '10px'
    badge.style.background = '#0284c7' // primary sky/blue
    badge.style.color = '#ffffff'
    badge.style.fontSize = '11px'
    badge.style.fontWeight = '700'
    badge.style.lineHeight = '20px'
    badge.style.textAlign = 'center'
    badge.style.boxShadow = '0 2px 4px rgba(0, 0, 0, 0.25)'
    badge.style.zIndex = '2'
    wrapper.appendChild(badge)
  } else {
    // Singola miniatura
    wrapper.style.height = '50px'
    wrapper.style.borderRadius = '8px'
    wrapper.style.border = '1px solid rgba(0, 0, 0, 0.15)'
    wrapper.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.16)'
    wrapper.style.overflow = 'hidden'
    wrapper.style.background = '#ffffff'

    const img = document.createElement('img')
    img.src = primaryUrl
    img.alt = ''
    img.style.width = '100%'
    img.style.height = '100%'
    img.style.objectFit = 'cover'
    img.style.display = 'block'
    wrapper.appendChild(img)
  }

  return wrapper
}

export function startDragPreview(
  event: DragEvent | React.DragEvent,
  options: DragPreviewOptions,
): HTMLElement | null {
  if (typeof document === 'undefined') return null

  stopDragPreview()

  // Sopprime l'anteprima nativa ingombrante
  const transparent = getTransparentDragImage()
  if (transparent && event.dataTransfer?.setDragImage) {
    try {
      event.dataTransfer.setDragImage(transparent, 0, 0)
    } catch {
      // Ignora se fallisce nel browser / mock
    }
  }

  const container = createDragPreviewDOM(options)

  // In basso a sinistra del cursore (larghezza 68 px + 18 px di distacco)
  const offsetX = -86
  const offsetY = 18

  if (event.clientX || event.clientY) {
    container.style.left = `${event.clientX + offsetX}px`
    container.style.top = `${event.clientY + offsetY}px`
  } else {
    container.style.display = 'none'
  }

  document.body.appendChild(container)

  const updatePosition = (clientX: number, clientY: number) => {
    if (clientX === 0 && clientY === 0) return
    container.style.display = 'block'
    container.style.left = `${clientX + offsetX}px`
    container.style.top = `${clientY + offsetY}px`
  }

  const onDragOver = (e: DragEvent) => {
    updatePosition(e.clientX, e.clientY)
  }

  const onDrag = (e: DragEvent) => {
    updatePosition(e.clientX, e.clientY)
  }

  const cleanup = () => {
    stopDragPreview()
  }

  window.addEventListener('dragover', onDragOver, { capture: true })
  window.addEventListener('drag', onDrag, { capture: true })
  window.addEventListener('dragend', cleanup, { capture: true })
  window.addEventListener('drop', cleanup, { capture: true })

  activeCleanupFn = () => {
    window.removeEventListener('dragover', onDragOver, { capture: true })
    window.removeEventListener('drag', onDrag, { capture: true })
    window.removeEventListener('dragend', cleanup, { capture: true })
    window.removeEventListener('drop', cleanup, { capture: true })
    if (container.parentElement) {
      container.parentElement.removeChild(container)
    }
  }

  return container
}

export function stopDragPreview(): void {
  if (activeCleanupFn) {
    activeCleanupFn()
    activeCleanupFn = null
  }
}
