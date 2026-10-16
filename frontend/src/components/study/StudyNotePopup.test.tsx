import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { StudyNotePopup } from './StudyNotePopup'
import type { StudyNote } from '@/api/studyNotes'

describe('StudyNotePopup', () => {
  it('rende il Markdown sanificato dell’API, con titoli, elenchi e formule', async () => {
    const note = {
      id: 1, lesson_id: 1, kind: 'chiedi', unit_id: '1.1',
      response: { spiegazione: '### Titolo\n**Forte**\n- Primo\n$a_1 * b_2$\n<script>alert(1)</script>' },
      spiegazione_html: '<h3>Titolo</h3><p><strong>Forte</strong></p><ul><li>Primo</li></ul><p>$a_1 * b_2$</p><p>&lt;script&gt;alert(1)&lt;/script&gt;</p>',
    } as StudyNote
    render(<StudyNotePopup open onClose={vi.fn()} kind="chiedi" unitId="1.1" quote="Citazione" note={note} />)
    const answer = screen.getByTestId('study-note-answer')
    expect(screen.getByRole('heading', { name: 'Titolo' })).toBeInTheDocument()
    expect(answer.querySelector('strong')).toHaveTextContent('Forte')
    expect(answer.querySelector('li')).toHaveTextContent('Primo')
    expect(answer.querySelector('script')).toBeNull()
    await waitFor(() => expect(answer.querySelector('math')).not.toBeNull())
  })

  it('↵ invia e ⇧↵ lascia scrivere una nuova riga', () => {
    const send = vi.fn()
    render(<StudyNotePopup open onClose={vi.fn()} kind="chiedi" unitId="1.1" quote="Un passaggio" onSend={send} />)
    const input = screen.getByTestId('study-note-input')
    fireEvent.change(input, { target: { value: 'Una domanda' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    expect(send).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(send).toHaveBeenCalledWith('Una domanda')
    expect(screen.getByTestId('study-note-composer').parentElement).toBe(screen.getByRole('dialog'))
  })

  it('misura dal vivo una citazione lunga e conserva il fondo fuori dallo scorrimento', () => {
    let resized: () => void = () => undefined
    vi.stubGlobal('ResizeObserver', class { constructor(callback: () => void) { resized = callback } observe() {} disconnect() {} })
    const rect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      return new DOMRect(0, 0, this.dataset.testid === 'study-note-popup' ? 440 : 0, this.dataset.testid === 'study-note-popup' ? 600 : 0)
    })
    const anchor = new DOMRect(950, 700, 30, 20)
    const { unmount } = render(<StudyNotePopup open onClose={vi.fn()} kind="chiedi" unitId="1.1" quote={'Citazione lunga. '.repeat(100)} anchorRect={anchor} />)
    const popup = screen.getByRole('dialog')
    expect(Number.parseFloat(popup.style.top)).toBeGreaterThanOrEqual(12)
    expect(Number.parseFloat(popup.style.top) + 600).toBeLessThanOrEqual(window.innerHeight - 12)
    expect(screen.getByTestId('study-note-quote').querySelector('.line-clamp-2')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Mostra tutto' }))
    expect(screen.getByTestId('study-note-quote').querySelector('.line-clamp-2')).toBeNull()
    resized()
    expect(screen.getByTestId('study-note-body')).toHaveClass('overflow-y-auto')
    unmount()
    rect.mockRestore()
    vi.unstubAllGlobals()
  })

  it('allarga a pannello e torna alla misura iniziale con doppio clic', () => {
    render(<StudyNotePopup open onClose={vi.fn()} kind="verifica" unitId="1.1" quote="Una citazione" />)
    fireEvent.click(screen.getByRole('button', { name: 'Allarga a pannello' }))
    expect(screen.getByRole('dialog')).toHaveStyle({ height: `${window.innerHeight}px`, top: '0px' })
    fireEvent.doubleClick(screen.getByTestId('study-note-header'))
    expect(screen.getByRole('dialog')).toHaveStyle({ width: '440px' })
    expect(screen.getByRole('button', { name: 'Allarga a pannello' })).toBeInTheDocument()
  })
  it('renders input mode for verifica and triggers onSend on button and ⌘↵', () => {
    const onSend = vi.fn()
    const onClose = vi.fn()

    const { rerender } = render(
      <StudyNotePopup
        open={true}
        onClose={onClose}
        kind="verifica"
        unitId="1.1"
        quote="La pressione arteriosa media è 93 mmHg."
        onSend={onSend}
      />,
    )

    expect(screen.getByRole('dialog', { name: 'Verifica' })).toBeInTheDocument()
    expect(screen.getByText('La pressione arteriosa media è 93 mmHg.')).toBeInTheDocument()
    const input = screen.getByPlaceholderText('Cosa vuoi verificare?')
    expect(input).toBeInTheDocument()

    // Test send via button
    fireEvent.change(input, { target: { value: 'È davvero 93 mmHg?' } })
    fireEvent.click(screen.getByTestId('study-note-submit'))
    expect(onSend).toHaveBeenCalledWith('È davvero 93 mmHg?')

    // Test send via ⌘↵
    fireEvent.keyDown(input, { key: 'Enter', metaKey: true })
    expect(onSend).toHaveBeenCalledTimes(2)

    // Test close via Esc key on textarea
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()

    // Test close via close button
    fireEvent.click(screen.getByTestId('study-note-close'))
    expect(onClose).toHaveBeenCalledTimes(2)

    // If open is false, nothing is rendered
    rerender(
      <StudyNotePopup
        open={false}
        onClose={onClose}
        kind="verifica"
        unitId="1.1"
        quote="La pressione arteriosa media è 93 mmHg."
      />,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders waiting state with spinner and helpful message', () => {
    render(
      <StudyNotePopup
        open={true}
        onClose={vi.fn()}
        kind="chiedi"
        unitId="1.2"
        quote="Il compenso renale richiede ore o giorni."
        isWaiting={true}
      />,
    )

    expect(screen.getByTestId('study-note-waiting')).toBeInTheDocument()
    expect(
      screen.getByText('Preparo la spiegazione con il modello della revisione…'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Puoi chiudere: la risposta arriva lo stesso e resta nella lezione.'),
    ).toBeInTheDocument()
  })

  it('renders result with verdict badge, explanation, proposed fix and calls onApply', () => {
    const onApply = vi.fn()
    const note: StudyNote = {
      id: 42,
      lesson_id: 1,
      unit_id: '1.1',
      unit_fingerprint: 'fp1',
      kind: 'verifica',
      anchor: { quote: '93 mmHg', prefix: '', suffix: '', start: 0, end: 7 },
      anchor_state: 'trovata',
      current_quote: '93 mmHg',
      request: 'Verifica il valore',
      response: {
        esito: 'errato',
        spiegazione: 'Il valore fisiologico è compreso tra 70 e 105 mmHg.',
        correzione: 'tra 70 e 105 mmHg',
      },
      model: 'gpt-4o',
      cost: 0.005,
      created_at: '2026-10-11T12:00:00Z',
      applied_decision_id: null,
    }

    render(
      <StudyNotePopup
        open={true}
        onClose={vi.fn()}
        kind="verifica"
        unitId="1.1"
        quote="93 mmHg"
        note={note}
        onApply={onApply}
      />,
    )

    expect(screen.getByTestId('study-note-verdict')).toHaveTextContent('Errato')
    expect(screen.getByTestId('study-note-answer')).toHaveTextContent(
      'Il valore fisiologico è compreso tra 70 e 105 mmHg.',
    )
    expect(screen.getByText('Correzione proposta')).toBeInTheDocument()
    expect(screen.getByText('tra 70 e 105 mmHg')).toBeInTheDocument()

    const applyBtn = screen.getByTestId('study-note-apply')
    expect(applyBtn).toBeEnabled()
    fireEvent.click(applyBtn)
    expect(onApply).toHaveBeenCalledWith(42)
  })

  it('shows applied state when applied_decision_id is present', () => {
    const note: StudyNote = {
      id: 42,
      lesson_id: 1,
      unit_id: '1.1',
      unit_fingerprint: 'fp1',
      kind: 'verifica',
      anchor: { quote: '93 mmHg', prefix: '', suffix: '', start: 0, end: 7 },
      anchor_state: 'trovata',
      current_quote: '93 mmHg',
      request: '',
      response: {
        esito: 'errato',
        spiegazione: 'Spiegazione',
        correzione: 'tra 70 e 105 mmHg',
      },
      model: 'gpt-4o',
      cost: 0.005,
      created_at: '2026-10-11T12:00:00Z',
      applied_decision_id: 10,
    }

    render(
      <StudyNotePopup
        open={true}
        onClose={vi.fn()}
        kind="verifica"
        unitId="1.1"
        quote="93 mmHg"
        note={note}
      />,
    )

    expect(screen.getByText('Correzione applicata')).toBeInTheDocument()
    expect(screen.queryByTestId('study-note-apply')).not.toBeInTheDocument()
  })

  it('shows warning when anchor state is cambiata or non_ritrovata', () => {
    const noteChanged: StudyNote = {
      id: 43,
      lesson_id: 1,
      unit_id: '1.1',
      unit_fingerprint: 'fp1',
      kind: 'chiedi',
      anchor: { quote: 'testo vecchio', prefix: '', suffix: '', start: 0, end: 13 },
      anchor_state: 'cambiata',
      current_quote: 'testo nuovo',
      request: '',
      response: { spiegazione: 'Spiegazione del testo' },
      model: 'gpt-4o',
      cost: 0.002,
      created_at: '2026-10-11T12:00:00Z',
    }

    const { rerender } = render(
      <StudyNotePopup
        open={true}
        onClose={vi.fn()}
        kind="chiedi"
        unitId="1.1"
        quote="testo vecchio"
        note={noteChanged}
      />,
    )

    expect(screen.getByText(/Il testo è cambiato dopo la domanda/)).toBeInTheDocument()
    expect(screen.getByText(/testo nuovo/)).toBeInTheDocument()

    const noteLost: StudyNote = {
      ...noteChanged,
      anchor_state: 'non_ritrovata',
    }

    rerender(
      <StudyNotePopup
        open={true}
        onClose={vi.fn()}
        kind="chiedi"
        unitId="1.1"
        quote="testo vecchio"
        note={noteLost}
      />,
    )

    expect(screen.getByText(/Passaggio non ritrovato/)).toBeInTheDocument()
  })
})
