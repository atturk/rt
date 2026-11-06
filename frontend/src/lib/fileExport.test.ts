import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { canShareFiles, fetchExport, saveFile, shareFile } from './fileExport'
import { clearFileStatus, getFileStatusSnapshot, trackFileExport } from './fileStatus'

describe('fileExport', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  describe('fetchExport', () => {
    it('estrae il nome dal filename*=UTF-8 di Content-Disposition', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        headers: new Headers({
          'content-disposition': "attachment; filename*=UTF-8''lezione%20prova.rt",
          'content-type': 'application/zip',
        }),
        blob: async () => new Blob(['dati'], { type: 'application/zip' }),
      } as unknown as Response)

      const file = await fetchExport('/api/export')
      expect(file.name).toBe('lezione prova.rt')
      expect(file.type).toBe('application/zip')
    })

    it('fallback su filename="..." di Content-Disposition se filename* manca', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        headers: new Headers({
          'content-disposition': 'attachment; filename="appunti.md"',
          'content-type': 'text/markdown',
        }),
        blob: async () => new Blob(['# test'], { type: 'text/markdown' }),
      } as unknown as Response)

      const file = await fetchExport('/api/export')
      expect(file.name).toBe('appunti.md')
      expect(file.type).toBe('text/markdown')
    })

    it('estrae il messaggio di errore dal body JSON in caso di errore HTTP', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: async () => ({ error: { message: 'PDF non disponibile senza Chromium' } }),
      } as unknown as Response)

      await expect(fetchExport('/api/export/pdf')).rejects.toThrow('PDF non disponibile senza Chromium')
    })

    it('genera errore generico se il JSON non ha error.message', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => null,
      } as unknown as Response)

      await expect(fetchExport('/api/export/pdf')).rejects.toThrow('Export non riuscito (500)')
    })
  })

  describe('saveFile', () => {
    it('crea un elemento <a>, clicca per scaricare e revoca l URL dopo 60 secondi', () => {
      const createObjectURL = vi.fn(() => 'blob:mock-url')
      const revokeObjectURL = vi.fn()
      URL.createObjectURL = createObjectURL
      URL.revokeObjectURL = revokeObjectURL

      const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
      const appendSpy = vi.spyOn(document.body, 'appendChild')
      const removeSpy = vi.spyOn(document.body, 'removeChild')

      const file = new File(['prova'], 'salva.md', { type: 'text/markdown' })
      saveFile(file)

      expect(createObjectURL).toHaveBeenCalledWith(file)
      expect(appendSpy).toHaveBeenCalled()
      expect(clickSpy).toHaveBeenCalled()
      expect(removeSpy).toHaveBeenCalled()

      expect(revokeObjectURL).not.toHaveBeenCalled()
      vi.advanceTimersByTime(59_999)
      expect(revokeObjectURL).not.toHaveBeenCalled()
      vi.advanceTimersByTime(2)
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
    })
  })

  describe('canShareFiles', () => {
    it('restituisce true se pywebview espone condividi', () => {
      const orig = (window as unknown as { pywebview?: unknown }).pywebview
      ;(window as unknown as { pywebview: { api: { condividi: unknown } } }).pywebview = { api: { condividi: vi.fn() } }
      expect(canShareFiles()).toBe(true)
      ;(window as unknown as { pywebview?: unknown }).pywebview = orig
    })

    it('restituisce true se navigator.canShare accetta i file', () => {
      const canShare = vi.fn().mockReturnValue(true)
      Object.assign(navigator, { canShare })
      expect(canShareFiles('application/pdf')).toBe(true)
      expect(canShare).toHaveBeenCalled()
    })

    it('restituisce false se navigator.canShare non accetta i file e pywebview manca', () => {
      const canShare = vi.fn().mockReturnValue(false)
      Object.assign(navigator, { canShare })
      expect(canShareFiles('application/pdf')).toBe(false)
    })
  })

  describe('shareFile', () => {
    it('chiama navigator.share con il file e il titolo', async () => {
      const share = vi.fn().mockResolvedValue(undefined)
      const canShare = vi.fn().mockReturnValue(true)
      Object.assign(navigator, { share, canShare })

      const file = new File(['pdf'], 'lezione.pdf', { type: 'application/pdf' })
      await shareFile(file, { title: 'Lezione 1' })

      expect(share).toHaveBeenCalledWith({
        files: [file],
        title: 'Lezione 1',
      })
    })

    it('ritenta con application/zip se un file .rt viene rifiutato da canShare', async () => {
      const share = vi.fn().mockResolvedValue(undefined)
      const canShare = vi.fn().mockImplementation(({ files }: { files: File[] }) => {
        return files[0].type === 'application/zip'
      })
      Object.assign(navigator, { share, canShare })

      const file = new File(['dati'], 'lezione.rt', { type: 'application/octet-stream' })
      await shareFile(file, { title: 'Lezione 1' })

      expect(share).toHaveBeenCalled()
      const sharedFile = share.mock.calls[0][0].files[0]
      expect(sharedFile.name).toBe('lezione.rt')
      expect(sharedFile.type).toBe('application/zip')
    })

    it('ignora silenziosamente AbortError se l utente chiude il menu di sistema', async () => {
      const abortError = new Error('User closed share sheet')
      abortError.name = 'AbortError'
      const share = vi.fn().mockRejectedValue(abortError)
      const canShare = vi.fn().mockReturnValue(true)
      Object.assign(navigator, { share, canShare })

      const file = new File(['pdf'], 'lezione.pdf', { type: 'application/pdf' })
      await expect(shareFile(file)).resolves.toBeUndefined()
    })

    it('NotAllowedError attiva il bottone Condividi nella barra di stato', async () => {
      clearFileStatus()
      const notAllowed = new Error('Permission denied')
      notAllowed.name = 'NotAllowedError'

      const file = new File(['pdf'], 'lezione.pdf', { type: 'application/pdf' })
      await trackFileExport(Promise.resolve(file), {
        busyMessage: 'Preparo il PDF…',
        doneLabel: 'PDF pronto',
        isShare: true,
        onShare: () => Promise.reject(notAllowed),
      })

      const snapshot = getFileStatusSnapshot()
      expect(snapshot.kind).toBe('ready')
      if (snapshot.kind === 'ready') {
        expect(snapshot.isShare).toBe(true)
        expect(snapshot.label).toBe('PDF pronto')
      }
    })
  })
})
