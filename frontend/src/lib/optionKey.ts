import { useEffect, useState } from 'react'

/**
 * True mentre è premuto Option (Alt): rivela le azioni distruttive (elimina lezione,
 * connessione, chiave) senza tenerle sempre in vista. Torna false quando la finestra perde il
 * focus, altrimenti un Cmd-Tab con Option premuto lascerebbe il pulsante visibile.
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

/** Classi di un pulsante che compare con Option o quando il gruppo (`group`) ha il focus da
 * tastiera; su mobile (niente Option) resta visibile. */
export function optionRevealClass(optionDown: boolean): string {
  return optionDown ? '' : 'md:opacity-0 md:group-focus-within:opacity-100'
}
