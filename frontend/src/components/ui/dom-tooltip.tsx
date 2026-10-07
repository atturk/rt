// oxlint-disable react/only-export-components -- Adattatore DOM dei widget, senza componenti pubblici.
import { useEffect, type KeyboardEvent } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { Tooltip, type TooltipTriggerProps } from './tooltip'

function DomTrigger({ node, trigger }: { node: HTMLElement; trigger: TooltipTriggerProps }) {
  const setTrigger = trigger.ref
  useEffect(() => { setTrigger(node); return () => { setTrigger(null) } }, [node, setTrigger])
  useEffect(() => {
    const handlers = { mouseenter: trigger.onMouseEnter, mouseleave: trigger.onMouseLeave, focus: trigger.onFocus, blur: trigger.onBlur, pointerdown: trigger.onPointerDown, keydown: (event: Event) => trigger.onKeyDown(event as unknown as KeyboardEvent) }
    for (const [name, handler] of Object.entries(handlers)) node.addEventListener(name, handler)
    if (trigger['aria-describedby']) node.setAttribute('aria-describedby', trigger['aria-describedby'])
    return () => {
      for (const [name, handler] of Object.entries(handlers)) node.removeEventListener(name, handler)
      node.removeAttribute('aria-describedby')
    }
  }, [node, trigger])
  return null
}

const roots = new Map<HTMLElement, { root: Root; host: HTMLElement; connected: boolean }>()
let observer: MutationObserver | undefined
/** Porta lo stesso Tooltip ai controlli creati da CodeMirror o dall'HTML del documento. */
export function mountDomTooltip(node: HTMLElement, content: string) {
  const host = document.createElement('span')
  host.hidden = true
  document.body.append(host)
  const root = createRoot(host)
  root.render(<Tooltip content={content}>{trigger => <DomTrigger node={node} trigger={trigger} />}</Tooltip>)
  roots.set(node, { root, host, connected: node.isConnected })
  observer ??= new MutationObserver(mutations => {
    for (const [element, entry] of roots) {
      if (element.isConnected) entry.connected = true
      else if (entry.connected || mutations.some(mutation => Array.from(mutation.removedNodes).some(removed => removed.contains(element)))) unmountDomTooltip(element)
    }
  })
  observer.observe(document.body, { childList: true, subtree: true })
  return () => unmountDomTooltip(node)
}
export function unmountDomTooltip(node: HTMLElement) {
  const entry = roots.get(node)
  if (!entry) return
  roots.delete(node)
  queueMicrotask(() => { entry.root.unmount(); entry.host.remove() })
  if (!roots.size) { observer?.disconnect(); observer = undefined }
}
