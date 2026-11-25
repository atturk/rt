import { describe, expect, it } from 'vitest'
import { createUnitShortcuts } from './unitShortcuts'

describe('createUnitShortcuts', () => {
  it('mostra solo Studia e Mettimi alla prova', () => {
    const node = createUnitShortcuts(1, '1.1', () => undefined)
    expect(node.querySelectorAll('a')).toHaveLength(2)
    expect(node.querySelector('button')).toBeNull()
  })
})
