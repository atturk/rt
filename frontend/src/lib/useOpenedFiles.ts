import { useEffect, useState } from 'react'

import type { OpenedFileItem } from '@/types/backup'
import { isAppWindow } from '@/lib/zoom'

export function useOpenedFiles(openNewLesson: (options?: { initialFiles?: File[] }) => void) {
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isAppWindow()) return

    const handleFiles = async (items: OpenedFileItem[]) => {
      if (!items || items.length === 0) return
      setError(null)
      try {
        const files = await Promise.all(
          items.map(async (item) => {
            const res = await fetch(`/api/v1/system/opened-files/${item.token}`)
            if (!res.ok) {
              const body = await res.json().catch(() => null)
              throw new Error(body?.error?.message || `Impossibile aprire ${item.name}`)
            }
            const blob = await res.blob()
            return new File([blob], item.name)
          })
        )
        if (files.length > 0) {
          openNewLesson({ initialFiles: files })
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore durante l'apertura del file.")
      }
    }

    window.rtOpenedFiles = handleFiles

    const pyApi = window.pywebview?.api
    if (pyApi?.file_in_attesa) {
      Promise.resolve(pyApi.file_in_attesa())
        .then((items) => {
          if (items && items.length > 0) {
            void handleFiles(items)
          }
        })
        .catch(() => {})
    }

    return () => {
      delete window.rtOpenedFiles
    }
  }, [openNewLesson])

  return { error, clearError: () => setError(null) }
}
