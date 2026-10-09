/** Le frecce della pagina non sottraggono mai un comando all'editor o ai controlli. */
export function lessonArrowAllowed(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return false
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return false
  const target = event.target instanceof Element ? event.target : null
  if (target?.closest('[data-testid="audio-player"], .cm-editor, input, textarea, select, [contenteditable], [role="slider"], [role="menu"], [role="listbox"], [role="dialog"]')) return false
  // Il player gestisce le frecce su window quando il mouse è sul suo riquadro.
  if (document.querySelector('[data-testid="audio-player"]:hover')) return false
  return !window.getSelection()?.toString() && !document.querySelector('dialog[open], [role="dialog"], [role="menu"], [role="listbox"]')
}

