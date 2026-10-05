import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { moveItem } from '@/lib/order'

import { AudioOrder } from './AudioOrder'

const file = (name: string) => new File(['x'], name, { lastModified: 1 })

afterEach(cleanup)

describe('AudioOrder', () => {
  it('sposta un elemento nella posizione di destinazione', () => {
    expect(moveItem(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a'])
    expect(moveItem(['a', 'b', 'c'], 2, 0)).toEqual(['c', 'a', 'b'])
    expect(moveItem(['a', 'b', 'c'], 1, 1)).toEqual(['a', 'b', 'c'])
  })

  it('riordina trascinando una riga su un\'altra', () => {
    const files = [file('1.m4a'), file('2.m4a'), file('3.m4a')]
    const onChange = vi.fn()
    render(<AudioOrder files={files} onChange={onChange} />)
    const rows = screen.getAllByTestId('audio-order-item')
    const data = new Map<string, string>()
    const dataTransfer = {
      setData: (k: string, v: string) => data.set(k, v), getData: (k: string) => data.get(k) ?? '',
      get types() { return [...data.keys()] }, effectAllowed: '', dropEffect: '',
    }
    fireEvent.dragStart(rows[0], { dataTransfer })
    fireEvent.dragOver(rows[2], { dataTransfer })
    fireEvent.drop(rows[2], { dataTransfer })
    expect(onChange).toHaveBeenCalledWith([files[1], files[2], files[0]])
  })

  it('ignora i file trascinati dal Finder e riordina con le frecce sulla maniglia', () => {
    const files = [file('1.m4a'), file('2.m4a')]
    const onChange = vi.fn()
    render(<AudioOrder files={files} onChange={onChange} />)
    const rows = screen.getAllByTestId('audio-order-item')
    fireEvent.drop(rows[0], { dataTransfer: { types: ['Files'], getData: () => '' } })
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.keyDown(screen.getByRole('button', { name: /Riordina 2\.m4a/ }), { key: 'ArrowUp' })
    expect(onChange).toHaveBeenCalledWith([files[1], files[0]])
  })
})
