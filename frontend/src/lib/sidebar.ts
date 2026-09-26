import { useCallback, useEffect, useState } from 'react'

const KEY = 'rt-sidebar-collapsed'

function initial(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

/** Barra laterale ridotta (solo da tablet in su): preferenza dell'interfaccia nel browser. */
export function useSidebarCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(initial)
  useEffect(() => {
    try {
      localStorage.setItem(KEY, collapsed ? '1' : '0')
    } catch {
      /* archiviazione non disponibile: vale solo per questa pagina */
    }
  }, [collapsed])
  const toggle = useCallback(() => setCollapsed((c) => !c), [])
  return [collapsed, toggle]
}
