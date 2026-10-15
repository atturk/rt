import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { GlobalFileDrop } from './GlobalFileDrop'

describe('GlobalFileDrop (UI3)', () => {
  it('mostra il velo quando si trascinano file accettati e chiama onDropFiles al rilascio', () => {
    const onDrop = vi.fn()
    render(<GlobalFileDrop onDropFiles={onDrop} />)

    expect(screen.queryByTestId('global-drop-veil')).not.toBeInTheDocument()

    const file = new File(['audio content'], 'lezione.mp3', { type: 'audio/mpeg' })
    const dt = {
      types: ['Files'],
      files: [file],
      items: [{ kind: 'file', type: 'audio/mpeg' }],
    }

    fireEvent.dragEnter(window, { dataTransfer: dt })
    expect(screen.getByTestId('global-drop-veil')).toBeInTheDocument()
    expect(screen.getByText('Rilascia per importare')).toBeInTheDocument()

    fireEvent.drop(window, { dataTransfer: dt })
    expect(screen.queryByTestId('global-drop-veil')).not.toBeInTheDocument()
    expect(onDrop).toHaveBeenCalledWith([file])
  })

  it('non mostra il velo per file non accettati', () => {
    const onDrop = vi.fn()
    render(<GlobalFileDrop onDropFiles={onDrop} />)

    const file = new File(['echo hello'], 'script.sh', { type: 'application/x-sh' })
    const dt = {
      types: ['Files'],
      files: [file],
      items: [{ kind: 'file', type: 'application/x-sh' }],
    }

    fireEvent.dragEnter(window, { dataTransfer: dt })
    expect(screen.queryByTestId('global-drop-veil')).not.toBeInTheDocument()
  })

  it('non mostra il velo per testo o link trascinati', () => {
    const onDrop = vi.fn()
    render(<GlobalFileDrop onDropFiles={onDrop} />)

    const dt = {
      types: ['text/plain'],
      files: [],
      items: [{ kind: 'string', type: 'text/plain' }],
    }

    fireEvent.dragEnter(window, { dataTransfer: dt })
    expect(screen.queryByTestId('global-drop-veil')).not.toBeInTheDocument()
  })

  it('non mostra il velo quando disabled è true (es. popup già aperto)', () => {
    const onDrop = vi.fn()
    render(<GlobalFileDrop disabled onDropFiles={onDrop} />)

    const file = new File(['pdf content'], 'slide.pdf', { type: 'application/pdf' })
    const dt = {
      types: ['Files'],
      files: [file],
      items: [{ kind: 'file', type: 'application/pdf' }],
    }

    fireEvent.dragEnter(window, { dataTransfer: dt })
    expect(screen.queryByTestId('global-drop-veil')).not.toBeInTheDocument()
  })

  it('si chiude premendo Escape', () => {
    const onDrop = vi.fn()
    render(<GlobalFileDrop onDropFiles={onDrop} />)

    const file = new File(['zip content'], 'bundle.zip', { type: 'application/zip' })
    const dt = {
      types: ['Files'],
      files: [file],
      items: [{ kind: 'file', type: 'application/zip' }],
    }

    fireEvent.dragEnter(window, { dataTransfer: dt })
    expect(screen.getByTestId('global-drop-veil')).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByTestId('global-drop-veil')).not.toBeInTheDocument()
  })

  it('si chiude quando il trascinamento esce dalla finestra', () => {
    const onDrop = vi.fn()
    render(<GlobalFileDrop onDropFiles={onDrop} />)

    const file = new File(['img content'], 'foto.jpg', { type: 'image/jpeg' })
    const dt = {
      types: ['Files'],
      files: [file],
      items: [{ kind: 'file', type: 'image/jpeg' }],
    }

    fireEvent.dragEnter(window, { dataTransfer: dt })
    expect(screen.getByTestId('global-drop-veil')).toBeInTheDocument()

    fireEvent.dragLeave(window, { relatedTarget: null, clientX: 0, clientY: 0 })
    expect(screen.queryByTestId('global-drop-veil')).not.toBeInTheDocument()
  })

  it('resta aperto passando da un elemento all\'altro, anche con relatedTarget null (Safari)', () => {
    vi.useFakeTimers()
    render(<GlobalFileDrop onDropFiles={vi.fn()} />)
    const dt = { types: ['Files'], files: [new File(['a'], 'lezione.mp3', { type: 'audio/mpeg' })],
      items: [{ kind: 'file', type: 'audio/mpeg' }] }
    fireEvent.dragEnter(window, { dataTransfer: dt })
    for (let i = 0; i < 5; i++) {
      fireEvent.dragLeave(window, { relatedTarget: null, clientX: 200, clientY: 200 })
      fireEvent.dragOver(window, { dataTransfer: dt, clientX: 210, clientY: 210 })
      act(() => { vi.advanceTimersByTime(300) })
    }
    expect(screen.getByTestId('global-drop-veil')).toBeInTheDocument()
    // Senza più dragover (trascinamento finito fuori dalla finestra) il velo si chiude.
    act(() => { vi.advanceTimersByTime(1000) })
    expect(screen.queryByTestId('global-drop-veil')).not.toBeInTheDocument()
    vi.useRealTimers()
  })
})
