import { afterEach, describe, expect, it, vi } from 'vitest'
import { createUnitShortcuts } from './unitShortcuts'

afterEach(() => { vi.restoreAllMocks() })

describe('createUnitShortcuts', () => {
  it('senza keywords mostra solo Studia e Mettimi alla prova', () => {
    const node = createUnitShortcuts(1, '1.1', () => undefined)
    expect(node.querySelectorAll('a')).toHaveLength(2)
    expect(node.querySelector('button')).toBeNull()
  })

  it('copia le keywords una per riga, anche con virgole interne', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const node = createUnitShortcuts(1, '1.1', () => undefined, ['Apolipoproteine (apoB-100, apoE)', 'LDL'])
    const button = node.querySelector('button')!
    expect(button.getAttribute('aria-label')).toBe("Copia le keywords dell'unità 1.1")
    button.click()
    expect(writeText).toHaveBeenCalledWith('Apolipoproteine (apoB-100, apoE)\nLDL')
  })
})
