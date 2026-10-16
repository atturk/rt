import { describe, expect, it } from 'vitest'
import {
  formatStripLabel,
  getStripClosedPreference,
  parseImageAlt,
  setStripClosedPreference,
} from './imageUtils'

describe('imageUtils', () => {
  describe('parseImageAlt', () => {
    it('estrae nome del documento e pagina con formato "pagina X"', () => {
      const res = parseImageAlt('4. Emostasi coagulazione trombosi embolia.pdf, pagina 3')
      expect(res.docName).toBe('4. Emostasi coagulazione trombosi embolia.pdf')
      expect(res.pageNumber).toBe(3)
    })

    it('estrae nome del documento e pagina con formato "p. X"', () => {
      const res = parseImageAlt('Ematologia.pdf, p. 14')
      expect(res.docName).toBe('Ematologia.pdf')
      expect(res.pageNumber).toBe(14)
    })

    it('estrae nome del documento e pagina con formato "pag. X"', () => {
      const res = parseImageAlt('Ematologia.pdf, pag. 5')
      expect(res.docName).toBe('Ematologia.pdf')
      expect(res.pageNumber).toBe(5)
    })

    it('gestisce testo senza indicazione di pagina', () => {
      const res = parseImageAlt('Schema della cascata coagulativa')
      expect(res.docName).toBe('Schema della cascata coagulativa')
      expect(res.pageNumber).toBeUndefined()
    })
  })

  describe('formatStripLabel', () => {
    it('formatta correttamente pagine consecutive dello stesso documento', () => {
      const images = [
        { src: '1.png', alt: '', docName: 'Emostasi.pdf', pageNumber: 3 },
        { src: '2.png', alt: '', docName: 'Emostasi.pdf', pageNumber: 4 },
        { src: '3.png', alt: '', docName: 'Emostasi.pdf', pageNumber: 5 },
        { src: '4.png', alt: '', docName: 'Emostasi.pdf', pageNumber: 6 },
      ]
      const { countPill, docLabel } = formatStripLabel(images)
      expect(countPill).toBe('4 pagine')
      expect(docLabel).toBe('Emostasi.pdf, p. 3–6')
    })

    it('formatta correttamente pagine non consecutive dello stesso documento', () => {
      const images = [
        { src: '1.png', alt: '', docName: 'Emostasi.pdf', pageNumber: 3 },
        { src: '2.png', alt: '', docName: 'Emostasi.pdf', pageNumber: 7 },
      ]
      const { countPill, docLabel } = formatStripLabel(images)
      expect(countPill).toBe('2 pagine')
      expect(docLabel).toBe('Emostasi.pdf, p. 3, 7')
    })

    it('formatta correttamente documenti diversi', () => {
      const images = [
        { src: '1.png', alt: '', docName: 'Doc1.pdf', pageNumber: 1 },
        { src: '2.png', alt: '', docName: 'Doc2.pdf', pageNumber: 2 },
      ]
      const { countPill, docLabel } = formatStripLabel(images)
      expect(countPill).toBe('2 pagine')
      expect(docLabel).toBe('Doc1.pdf, Doc2.pdf')
    })

    it('gestisce una sola pagina', () => {
      const images = [{ src: '1.png', alt: '', docName: 'Doc.pdf', pageNumber: 10 }]
      const { countPill, docLabel } = formatStripLabel(images)
      expect(countPill).toBe('1 pagina')
      expect(docLabel).toBe('Doc.pdf, p. 10')
    })
  })

  describe('preference', () => {
    it('salva e legge la preferenza strip_closed e invia l’evento', () => {
      let dispatched = false
      const listener = (e: Event) => {
        const custom = e as CustomEvent<{ closed: boolean }>
        if (custom.detail.closed === true) dispatched = true
      }
      window.addEventListener('rt-strip-toggle', listener)
      setStripClosedPreference(true)
      expect(getStripClosedPreference()).toBe(true)
      expect(dispatched).toBe(true)

      setStripClosedPreference(false)
      expect(getStripClosedPreference()).toBe(false)
      window.removeEventListener('rt-strip-toggle', listener)
    })
  })
})
