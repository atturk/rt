import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mockNavigate = vi.fn()
vi.mock('react-router', () => ({
  useNavigate: () => mockNavigate,
}))

import { useOpenedFiles } from './useOpenedFiles'

describe('useOpenedFiles', () => {
  beforeEach(() => {
    sessionStorage.setItem('rt-app', '1')
    window.pywebview = {
      api: {
        salva_copia_backup: vi.fn(),
        file_in_attesa: vi.fn().mockResolvedValue([]),
        importa_collezione: vi.fn(),
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

  it('caso 1: .rt e .zip di lezioni aprono l import di lezioni', async () => {
    const openNewLesson = vi.fn()
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      return Promise.resolve(new Response('zip content', {
        status: 200,
        headers: { 'content-type': 'application/zip' },
      }))
    })

    renderHook(() => useOpenedFiles(openNewLesson))

    await act(async () => {
      await window.rtOpenedFiles?.([
        { token: 'tok-rt', name: 'lezione.rt', size: 200 },
        { token: 'tok-zip', name: 'vecchia.zip', size: 300 },
      ])
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/system/opened-files/tok-rt')
    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/system/opened-files/tok-zip')
    expect(openNewLesson).toHaveBeenCalledTimes(1)
    const files = openNewLesson.mock.calls[0][0].initialFiles
    expect(files).toHaveLength(2)
    expect(files[0].name).toBe('lezione.rt')
    expect(files[1].name).toBe('vecchia.zip')
  })

  it('caso 2: .rtcal naviga a Impostazioni -> Calendario e non chiama /calendar/import', async () => {
    const openNewLesson = vi.fn()
    const navigate = vi.fn()
    const calendarData = { format: 'rt-calendar', version: 1, entries: [] }

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(calendarData), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    )

    renderHook(() => useOpenedFiles(openNewLesson, navigate))

    await act(async () => {
      await window.rtOpenedFiles?.([
        { token: 'tok-cal', name: 'orario.rtcal', size: 150 },
      ])
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/system/opened-files/tok-cal')
    // Non chiama l'import del calendario
    expect(fetchSpy).not.toHaveBeenCalledWith(expect.stringContaining('/calendar/import'), expect.anything())
    // Non apre Nuova lezione
    expect(openNewLesson).not.toHaveBeenCalled()
    // Naviga a Impostazioni -> Calendario con lo state
    expect(navigate).toHaveBeenCalledWith('/impostazioni/calendario', {
      state: { importCalendarFile: { name: 'orario.rtcal', data: calendarData } },
    })
  })

  it('caso 3: .rtdb chiama il gestore Python e non scarica il file nel frontend', async () => {
    const openNewLesson = vi.fn()
    const navigate = vi.fn()
    const fetchSpy = vi.spyOn(globalThis, 'fetch')

    renderHook(() => useOpenedFiles(openNewLesson, navigate))

    await act(async () => {
      await window.rtOpenedFiles?.([
        { token: 'tok-backup', name: 'collezione.rtdb', size: 5000 },
      ])
    })

    // Il frontend non scarica mai un .rtdb come allegato
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(openNewLesson).not.toHaveBeenCalled()
    expect(navigate).not.toHaveBeenCalled()
    // Chiama il backend Python con il token
    expect(window.pywebview?.api?.importa_collezione).toHaveBeenCalledWith('tok-backup')
  })

  it('caso 4: tutto il resto scarica il file e apre Nuova lezione', async () => {
    const openNewLesson = vi.fn()
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('audio/pdf content', {
        status: 200,
        headers: { 'content-type': 'application/pdf' },
      })
    )

    renderHook(() => useOpenedFiles(openNewLesson))

    await act(async () => {
      await window.rtOpenedFiles?.([
        { token: 'tok-pdf', name: 'slide.pdf', size: 100 },
      ])
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/system/opened-files/tok-pdf')
    expect(openNewLesson).toHaveBeenCalledTimes(1)
    const calledArgs = openNewLesson.mock.calls[0][0]
    expect(calledArgs.initialFiles[0].name).toBe('slide.pdf')
  })

  it('apertura a freddo: smista correttamente i file da file_in_attesa', async () => {
    const openNewLesson = vi.fn()
    const navigate = vi.fn()

    window.pywebview = {
      api: {
        salva_copia_backup: vi.fn(),
        file_in_attesa: vi.fn().mockResolvedValue([
          { token: 'tok-cold-rtdb', name: 'RT-2026-11-03.rtdb', size: 9000 },
        ]),
        importa_collezione: vi.fn(),
      },
    }

    renderHook(() => useOpenedFiles(openNewLesson, navigate))

    await waitFor(() => {
      expect(window.pywebview?.api?.importa_collezione).toHaveBeenCalledWith('tok-cold-rtdb')
    })
    expect(openNewLesson).not.toHaveBeenCalled()
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
