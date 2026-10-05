import { useEffect, useState } from 'react'

import { usePreference } from './preferences'

export type Theme = 'light' | 'dark'
export type ThemePreference = 'sistema' | 'chiaro' | 'scuro'

/** Sistema segue anche i cambi di tema del dispositivo a pagina già aperta. */
export function useTheme(): [Theme, () => void] {
  const [preference, setPreference] = usePreference<ThemePreference>('theme', 'sistema')
  const [systemDark, setSystemDark] = useState(() => globalThis.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false)
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const changed = () => setSystemDark(media.matches)
    media.addEventListener('change', changed)
    return () => media.removeEventListener('change', changed)
  }, [])
  const theme = preference === 'scuro' || (preference === 'sistema' && systemDark) ? 'dark' : 'light'
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])
  return [theme, () => setPreference(theme === 'dark' ? 'chiaro' : 'scuro')]
}
