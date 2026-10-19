import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { getZoom, setZoom, zoomIn, zoomOut, resetZoom, zoomed, isAppWindow, handleZoomKeydown } from './zoom'

describe('zoom', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    document.documentElement.style.zoom = ''
  })

  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    document.documentElement.style.zoom = ''
  })

  it('valore iniziale 1 e resetZoom', () => {
    expect(getZoom()).toBe(1)
    setZoom(1.5)
    expect(getZoom()).toBe(1.5)
    resetZoom()
    expect(getZoom()).toBe(1)
    expect(document.documentElement.style.zoom).toBe('1')
  })

  it('zoomIn da 1 va a 1.1 e si ferma a 2', () => {
    resetZoom()
    zoomIn()
    expect(getZoom()).toBe(1.1)
    expect(document.documentElement.style.zoom).toBe('1.1')
    expect(localStorage.getItem('rt-device:zoom')).toBe('1.1')

    // Raggiungi il massimo
    for (let i = 0; i < 10; i++) {
      zoomIn()
    }
    expect(getZoom()).toBe(2)
    zoomIn()
    expect(getZoom()).toBe(2)
  })

  it('zoomOut si ferma a 0.67', () => {
    resetZoom()
    zoomOut()
    expect(getZoom()).toBe(0.9)

    // Raggiungi il minimo
    for (let i = 0; i < 10; i++) {
      zoomOut()
    }
    expect(getZoom()).toBe(0.67)
    zoomOut()
    expect(getZoom()).toBe(0.67)
  })

  it('invia evento rt-zoom-change', () => {
    const listener = vi.fn()
    window.addEventListener('rt-zoom-change', listener)
    setZoom(1.25)
    expect(listener).toHaveBeenCalled()
    const event = listener.mock.calls[0][0] as CustomEvent<{ zoom: number }>
    expect(event.detail.zoom).toBe(1.25)
    window.removeEventListener('rt-zoom-change', listener)
  })

  it('funziona anche se localStorage lancia eccezioni', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('Accesso negato')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('Accesso negato')
    })

    expect(getZoom()).toBe(1)
    expect(() => setZoom(1.25)).not.toThrow()
    expect(document.documentElement.style.zoom).toBe('1.25')
  })

  it('zoomed(px) scala le coordinate per il livello di zoom', () => {
    setZoom(1)
    expect(zoomed(100)).toBe(100)
    setZoom(2)
    expect(zoomed(100)).toBe(50)
  })

  it('scorciatoie interfaccia: con segnale app ingrandisce e fa preventDefault, senza non fa nulla', () => {
    resetZoom()
    // Senza segnale app
    const eventWithoutApp = new KeyboardEvent('keydown', { key: '=', ctrlKey: true, cancelable: true })
    const handledWithout = handleZoomKeydown(eventWithoutApp)
    expect(handledWithout).toBe(false)
    expect(eventWithoutApp.defaultPrevented).toBe(false)
    expect(getZoom()).toBe(1)

    // Con segnale app
    sessionStorage.setItem('rt-app', '1')
    expect(isAppWindow()).toBe(true)

    const eventWithApp = new KeyboardEvent('keydown', { key: '=', ctrlKey: true, cancelable: true })
    const handledWith = handleZoomKeydown(eventWithApp)
    expect(handledWith).toBe(true)
    expect(eventWithApp.defaultPrevented).toBe(true)
    expect(getZoom()).toBe(1.1)

    const eventMinus = new KeyboardEvent('keydown', { key: '-', ctrlKey: true, cancelable: true })
    handleZoomKeydown(eventMinus)
    expect(eventMinus.defaultPrevented).toBe(true)
    expect(getZoom()).toBe(1)

    const eventZero = new KeyboardEvent('keydown', { key: '0', ctrlKey: true, cancelable: true })
    setZoom(1.5)
    handleZoomKeydown(eventZero)
    expect(eventZero.defaultPrevented).toBe(true)
    expect(getZoom()).toBe(1)
  })

  it('window.rtZoom chiama zoom in, out e reset', () => {
    resetZoom()
    expect(window.rtZoom).toBeDefined()
    window.rtZoom!('in')
    expect(getZoom()).toBe(1.1)
    window.rtZoom!('out')
    expect(getZoom()).toBe(1)
    setZoom(1.5)
    window.rtZoom!('reset')
    expect(getZoom()).toBe(1)
  })
})
