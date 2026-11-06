import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fetchExport, saveFile } from './fileExport'

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
})
