import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import type { OpenedFileItem } from '@/types/backup'
import { isAppWindow } from '@/lib/zoom'

export function useOpenedFiles(
  openNewLesson: (options?: { initialFiles?: File[] }) => void,
  navigateFn?: (path: string, options?: { state?: unknown }) => void,
) {
  const [error, setError] = useState<string | null>(null)
  const routerNavigate = useNavigate()
  const navigate = navigateFn ?? routerNavigate

  useEffect(() => {
    if (!isAppWindow()) return

    const handleFiles = async (items: OpenedFileItem[]) => {
      if (!items || items.length === 0) return
      setError(null)
      try {
        const lessonFiles: OpenedFileItem[] = []
        for (const item of items) {
          const lower = item.name.toLowerCase()
          if (lower.endsWith('.rtdb')) {
            // Lato Python: _import_collection
            window.pywebview?.api?.importa_collezione?.(item.token)
          } else if (lower.endsWith('.rtcal')) {
            // Calendario: naviga a Impostazioni -> Calendario con state
            const res = await fetch(`/api/v1/system/opened-files/${item.token}`)
            if (!res.ok) {
              const body = await res.json().catch(() => null)
              throw new Error(body?.error?.message || `Impossibile aprire ${item.name}`)
            }
            const text = await res.text()
            const data = JSON.parse(text) as Record<string, unknown>
            navigate?.('/impostazioni/calendario', {
              state: { importCalendarFile: { name: item.name, data } },
            })
          } else {
            // .rt, .zip, o file di lezione (audio, documenti, ecc.)
            lessonFiles.push(item)
          }
        }

        if (lessonFiles.length > 0) {
          const files = await Promise.all(
            lessonFiles.map(async (item) => {
              const res = await fetch(`/api/v1/system/opened-files/${item.token}`)
              if (!res.ok) {
                const body = await res.json().catch(() => null)
                throw new Error(body?.error?.message || `Impossibile aprire ${item.name}`)
              }
              const blob = await res.blob()
              return new File([blob], item.name)
            }),
          )
          if (files.length > 0) {
            openNewLesson({ initialFiles: files })
          }
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
  }, [openNewLesson, navigate])

  return { error, clearError: () => setError(null) }
}
