let activeCleanupFn: (() => void) | null = null
let transparentImg: HTMLImageElement | null = null

export const BAN_CLASS = 'rt-drag-preview-ban'

function getTransparentDragImage(): HTMLImageElement {
  if (!transparentImg && typeof Image !== 'undefined') {
    transparentImg = new Image()
    transparentImg.src =
      'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
  }
  return transparentImg as HTMLImageElement
}

function createBanIconDOM(stack: boolean): HTMLElement {
  const badge = document.createElement('div')
  badge.className = `${BAN_CLASS} flex items-center justify-center`
  badge.setAttribute('data-testid', 'drag-preview-ban')
  badge.style.position = 'absolute'
  badge.style.top = '-6px'
  if (stack) {
    badge.style.left = '-6px'
  } else {
    badge.style.right = '-6px'
  }
  badge.style.width = '20px'
  badge.style.height = '20px'
  badge.style.borderRadius = '50%'
  badge.style.backgroundColor = '#ef4444' // red-500
  badge.style.color = '#ffffff'
  badge.style.display = 'flex'
  badge.style.alignItems = 'center'
  badge.style.justifyContent = 'center'
  badge.style.boxShadow = '0 2px 4px rgba(0, 0, 0, 0.25)'
  badge.style.zIndex = '10'
  badge.innerHTML =
    '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-ban"><circle cx="12" cy="12" r="10"/><path d="M4.929 4.929 19.07 19.071"/></svg>'
  return badge
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
    wrapper.style.background = '#ffffff'

    const img = document.createElement('img')
    img.src = primaryUrl
    img.alt = ''
    img.style.width = '100%'
    img.style.height = '100%'
    img.style.borderRadius = '7px'
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
  const isStack = (options.count ?? options.urls.length) > 1

  // In basso a destra del cursore: si trascina da destra (pannello Media) verso sinistra (testo)
  const offsetX = 18
  const offsetY = 18

  let lastX = event.clientX || 0
  let lastY = event.clientY || 0

  if (event.clientX || event.clientY) {
    container.style.left = `${event.clientX + offsetX}px`
    container.style.top = `${event.clientY + offsetY}px`
  } else {
    container.style.display = 'none'
  }

  document.body.appendChild(container)

  const setBan = (banned: boolean) => {
    const existing = container.querySelector(`.${BAN_CLASS}`)
    if (banned) {
      if (!existing) {
        container.appendChild(createBanIconDOM(isStack))
      }
    } else {
      if (existing) {
        existing.remove()
      }
    }
  }

  // All'inizio dell'azione di trascinamento siamo sopra l'elemento di origine (zona non di rilascio)
  setBan(true)

  const updatePosition = (clientX: number, clientY: number) => {
    // In WebKit su elementi non di rilascio le coordinate possono arrivare a (0, 0).
    // In tal caso preserviamo l'ultima posizione valida nota.
    if (clientX === 0 && clientY === 0) {
      if (lastX !== 0 || lastY !== 0) {
        container.style.display = 'block'
        container.style.left = `${lastX + offsetX}px`
        container.style.top = `${lastY + offsetY}px`
      }
      return
    }
    lastX = clientX
    lastY = clientY
    container.style.display = 'block'
    container.style.left = `${clientX + offsetX}px`
    container.style.top = `${clientY + offsetY}px`
  }

  const onDragOverCapture = (e: DragEvent) => {
    updatePosition(e.clientX, e.clientY)
    // preventDefault permette a WebKit di continuare a inviare eventi dragover con coordinate corrette su tutta la finestra
    e.preventDefault()
  }

  const onDragOverBubble = (e: DragEvent) => {
    const effect = e.dataTransfer?.dropEffect
    const isAllowed = effect === 'copy' || effect === 'move'
    if (isAllowed) {
      setBan(false)
    } else {
      try {
        if (e.dataTransfer) {
          e.dataTransfer.dropEffect = 'none'
        }
      } catch {
        // Ignora se non scrivibile
      }
      setBan(true)
    }
  }

  const onDrag = (e: DragEvent) => {
    updatePosition(e.clientX, e.clientY)
  }

  const onDrop = (e: DragEvent) => {
    const effect = e.dataTransfer?.dropEffect
    const isAllowed = effect === 'copy' || effect === 'move'
    if (!isAllowed) {
      e.preventDefault()
    }
    stopDragPreview()
  }

  const cleanup = () => {
    stopDragPreview()
  }

  window.addEventListener('dragover', onDragOverCapture, { capture: true })
  window.addEventListener('dragover', onDragOverBubble, { capture: false })
  document.addEventListener('dragover', onDragOverCapture, { capture: true })
  document.addEventListener('dragover', onDragOverBubble, { capture: false })
  window.addEventListener('drag', onDrag, { capture: true })
  window.addEventListener('dragend', cleanup, { capture: true })
  document.addEventListener('dragend', cleanup, { capture: true })
  window.addEventListener('drop', onDrop, { capture: true })
  document.addEventListener('drop', onDrop, { capture: true })

  activeCleanupFn = () => {
    window.removeEventListener('dragover', onDragOverCapture, { capture: true })
    window.removeEventListener('dragover', onDragOverBubble, { capture: false })
    document.removeEventListener('dragover', onDragOverCapture, { capture: true })
    document.removeEventListener('dragover', onDragOverBubble, { capture: false })
    window.removeEventListener('drag', onDrag, { capture: true })
    window.removeEventListener('dragend', cleanup, { capture: true })
    document.removeEventListener('dragend', cleanup, { capture: true })
    window.removeEventListener('drop', onDrop, { capture: true })
    document.removeEventListener('drop', onDrop, { capture: true })
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
