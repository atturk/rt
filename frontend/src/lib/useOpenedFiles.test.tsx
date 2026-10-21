import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useOpenedFiles } from './useOpenedFiles'

describe('useOpenedFiles', () => {
  beforeEach(() => {
    sessionStorage.setItem('rt-app', '1')
    window.pywebview = {
      api: {
        salva_copia_backup: vi.fn(),
        file_in_attesa: vi.fn().mockResolvedValue([]),
      },
    }
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    sessionStorage.clear()
    delete (window as unknown as { pywebview?: unknown }).pywebview
    delete window.rtOpenedFiles
  })

  it('registra e rimuove window.rtOpenedFiles in ambiente desktop', () => {
    const openNewLesson = vi.fn()
    const { unmount } = renderHook(() => useOpenedFiles(openNewLesson))

    expect(typeof window.rtOpenedFiles).toBe('function')
    unmount()
    expect(window.rtOpenedFiles).toBeUndefined()
  })

  it('non registra il callback se non è una finestra desktop', () => {
    sessionStorage.clear()
    delete (window as unknown as { pywebview?: unknown }).pywebview
    const openNewLesson = vi.fn()
    renderHook(() => useOpenedFiles(openNewLesson))

    expect(window.rtOpenedFiles).toBeUndefined()
  })

  it('scarica il file dal token e chiama openNewLesson', async () => {
    const openNewLesson = vi.fn()
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('contenuto file', {
        status: 200,
        headers: { 'content-type': 'application/pdf' },
      })
    )

    renderHook(() => useOpenedFiles(openNewLesson))

    await act(async () => {
      await window.rtOpenedFiles?.([
        { token: 'tok-123', name: 'lezione.pdf', size: 100 },
      ])
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/system/opened-files/tok-123')
    expect(openNewLesson).toHaveBeenCalledTimes(1)
    const calledArgs = openNewLesson.mock.calls[0][0]
    expect(calledArgs.initialFiles).toHaveLength(1)
    expect(calledArgs.initialFiles[0].name).toBe('lezione.pdf')
  })

  it('chiama file_in_attesa all avvio se disponibile in pywebview', async () => {
    const openNewLesson = vi.fn()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('contenuto docx', {
        status: 200,
        headers: { 'content-type': 'application/vnd.openxmlformats' },
      })
    )

    window.pywebview = {
      api: {
        salva_copia_backup: vi.fn(),
        file_in_attesa: vi.fn().mockResolvedValue([
          { token: 'tok-init', name: 'appunti.docx', size: 50 },
        ]),
      },
    }

    renderHook(() => useOpenedFiles(openNewLesson))

    await waitFor(() => {
      expect(openNewLesson).toHaveBeenCalledTimes(1)
    })
    const calledArgs = openNewLesson.mock.calls[0][0]
    expect(calledArgs.initialFiles[0].name).toBe('appunti.docx')
  })

  it('imposta lerrore se lo scaricamento fallisce', async () => {
    const openNewLesson = vi.fn()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: { message: 'Token scaduto' } }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      })
    )

    const { result } = renderHook(() => useOpenedFiles(openNewLesson))

    await act(async () => {
      await window.rtOpenedFiles?.([
        { token: 'tok-bad', name: 'rotto.pdf', size: 10 },
      ])
    })

    expect(result.current.error).toBe('Token scaduto')
    expect(openNewLesson).not.toHaveBeenCalled()
  })
})
