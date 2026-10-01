import { useEffect, useState } from 'react'

/**
 * True mentre è premuto Option (Alt): rivela le azioni nascoste o alternative (elimina lezione,
 * connessione, chiave; "Valida" al posto di "Esegui" nelle fasi) senza tenerle sempre in vista.
 * Torna false quando la finestra perde il focus, altrimenti un Cmd-Tab con Option premuto
 * lascerebbe il pulsante visibile.
 */
export function useOptionKey(): boolean {
  const [down, setDown] = useState(false)
  useEffect(() => {
    const onDown = (event: KeyboardEvent) => { if (event.key === 'Alt') setDown(true) }
    const onUp = (event: KeyboardEvent) => { if (event.key === 'Alt') setDown(false) }
    const reset = () => setDown(false)
    window.addEventListener('keydown', onDown)
    window.addEventListener('keyup', onUp)
    window.addEventListener('blur', reset)
    return () => {
      window.removeEventListener('keydown', onDown)
      window.removeEventListener('keyup', onUp)
      window.removeEventListener('blur', reset)
    }
  }, [])
  return down
}

/**
 * Come useOptionKey, distinguendo Option da Option+Shift: con Option+Shift le azioni di
 * download scaricano l'archivio completo invece del Markdown.
 */
export function useOptionShiftKeys(): { option: boolean; shift: boolean } {
  const [keys, setKeys] = useState({ option: false, shift: false })
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // Su macOS keydown di Alt ha già altKey; keyup no: gli stati si leggono dall'evento.
      const option = event.key === 'Alt' ? event.type === 'keydown' : event.altKey
      const shift = event.key === 'Shift' ? event.type === 'keydown' : event.shiftKey
      setKeys((current) => (current.option === option && current.shift === shift ? current : { option, shift }))
    }
    const reset = () => setKeys({ option: false, shift: false })
    window.addEventListener('keydown', onKey)
    window.addEventListener('keyup', onKey)
    window.addEventListener('blur', reset)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('keyup', onKey)
      window.removeEventListener('blur', reset)
    }
  }, [])
  return keys
}

/** Classi di un pulsante che compare con Option o quando il gruppo (`group`) ha il focus da
 * tastiera; su mobile (niente Option) resta visibile. */
export function optionRevealClass(optionDown: boolean): string {
  return optionDown ? '' : 'md:opacity-0 md:group-focus-within:opacity-100'
}
