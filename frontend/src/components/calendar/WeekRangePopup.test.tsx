import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import { WeekRangePopup } from './WeekRangePopup'

const anchor = { x: 100, y: 100, width: 20, height: 20 }
const entries = [{ id: 1, day_of_week: 0, start_time: '09:00', end_time: '11:00', materia: 'Analisi', valid_from: '2026-10-12', valid_to: '2026-10-26' }]

function open(onConfirm = vi.fn(), onClose = vi.fn(), initial?: Parameters<typeof WeekRangePopup>[0]['initial']) {
  const result = render(<WeekRangePopup anchor={anchor} currentDate="2026-10-19" entries={entries} initial={initial} onConfirm={onConfirm} onClose={onClose} />)
  const week = (date: string) => result.container.querySelector<HTMLButtonElement>(`[data-week="${date}"]`)!
  return { ...result, week, onConfirm, onClose }
}

it('mostra occupazione e cambi di versione, con 52 settimane nell’anno accademico 2026/27', () => {
  const { week, container } = open()
  expect(container.querySelectorAll('[data-week]')).toHaveLength(52)
  expect(week('2026-10-12')).toHaveClass('occupata')
  expect(week('2026-10-05')).not.toHaveClass('occupata')
  expect(week('2026-10-12')).toHaveAttribute('data-changed', 'true')
  expect(week('2026-10-19')).toHaveAttribute('data-changed', 'false')
  expect(week('2026-10-26')).toHaveAttribute('data-changed', 'true')
  expect(week('2026-10-12')).toHaveAccessibleName(/2 ore/)
})

it('si ferma al 2025 e al 2035', () => {
  open()
  fireEvent.click(screen.getByRole('button', { name: 'Anno precedente' }))
  expect(screen.getByTestId('calendar-range-year')).toHaveTextContent('2025')
  expect(screen.getByRole('button', { name: 'Anno precedente' })).toHaveAttribute('aria-disabled', 'true')
  for (let i = 0; i < 10; i++) fireEvent.click(screen.getByRole('button', { name: 'Anno successivo' }))
  expect(screen.getByTestId('calendar-range-year')).toHaveTextContent('2035')
  expect(screen.getByRole('button', { name: 'Anno successivo' })).toHaveAttribute('aria-disabled', 'true')
})

it('clic singolo seleziona solo quella settimana, abilita la conferma e aggiorna il conteggio', () => {
  const { week, onConfirm } = open()
  const confirm = screen.getByRole('button', { name: 'Modifica queste settimane' })
  expect(confirm).toHaveAttribute('aria-disabled', 'true')
  expect(screen.getByText('0 settimane selezionate')).toHaveAttribute('aria-live', 'polite')

  fireEvent.click(week('2026-10-12'))
  expect(week('2026-10-12')).toHaveAttribute('aria-pressed', 'true')
  expect(week('2026-10-12')).toHaveClass('bg-(--acc)', 'text-white')
  expect(screen.getByText('1 settimana selezionata')).toBeVisible()
  expect(confirm).not.toHaveAttribute('aria-disabled', 'true')

  fireEvent.click(week('2026-10-19'))
  expect(week('2026-10-12')).toHaveAttribute('aria-pressed', 'false')
  expect(week('2026-10-19')).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByText('1 settimana selezionata')).toBeVisible()

  fireEvent.click(confirm)
  expect(onConfirm).toHaveBeenCalledWith([{ from: '2026-10-19', to: '2026-10-26' }])
})

it('trascinamento da settimana 49 a 52 seleziona dal vivo tutte le settimane intermedie', () => {
  const { week, onConfirm } = open()
  // Nel 2026/27: 2026-11-30 = sett. 49, 2026-12-07 = 50, 2026-12-14 = 51, 2026-12-21 = 52
  fireEvent.pointerDown(week('2026-11-30'), { button: 0, pointerId: 1 })
  expect(screen.getByText('1 settimana selezionata')).toBeVisible()
  fireEvent.pointerEnter(week('2026-12-07'))
  expect(screen.getByText('2 settimane selezionate')).toBeVisible()
  fireEvent.pointerEnter(week('2026-12-21'))
  expect(screen.getByText('4 settimane selezionate')).toBeVisible()
  for (const w of ['2026-11-30', '2026-12-07', '2026-12-14', '2026-12-21']) {
    expect(week(w)).toHaveAttribute('aria-pressed', 'true')
  }
  fireEvent.pointerUp(week('2026-12-21'), { pointerId: 1 })
  fireEvent.click(screen.getByRole('button', { name: 'Modifica queste settimane' }))
  expect(onConfirm).toHaveBeenCalledWith([{ from: '2026-11-30', to: '2026-12-28' }])
})

it('⌘+clic e Ctrl+clic aggiungono e tolgono singole settimane senza perdere le altre', () => {
  const { week } = open()
  fireEvent.click(week('2026-10-12'))
  fireEvent.click(week('2026-10-26'), { metaKey: true })
  fireEvent.click(week('2026-11-02'), { ctrlKey: true })
  expect(screen.getByText('3 settimane selezionate')).toBeVisible()
  expect(week('2026-10-12')).toHaveAttribute('aria-pressed', 'true')
  expect(week('2026-10-26')).toHaveAttribute('aria-pressed', 'true')
  expect(week('2026-11-02')).toHaveAttribute('aria-pressed', 'true')

  fireEvent.click(week('2026-10-26'), { metaKey: true })
  expect(screen.getByText('2 settimane selezionate')).toBeVisible()
  expect(week('2026-10-26')).toHaveAttribute('aria-pressed', 'false')
  expect(week('2026-10-12')).toHaveAttribute('aria-pressed', 'true')
  expect(week('2026-11-02')).toHaveAttribute('aria-pressed', 'true')
})

it.each([false, true])('⇧+clic dall’àncora seleziona l’intervallo in ordine diretto o inverso: %s', reverse => {
  const { week, onConfirm } = open()
  fireEvent.click(week('2026-10-05'))
  fireEvent.click(week(reverse ? '2026-10-26' : '2026-10-19'), { metaKey: true })
  fireEvent.click(week(reverse ? '2026-10-19' : '2026-10-26'), { shiftKey: true })
  expect(screen.getByText('3 settimane selezionate')).toBeVisible()
  expect(week('2026-10-05')).toHaveAttribute('aria-pressed', 'true')
  expect(week('2026-10-19')).toHaveAttribute('aria-pressed', 'true')
  expect(week('2026-10-26')).toHaveAttribute('aria-pressed', 'true')

  fireEvent.click(screen.getByRole('button', { name: 'Modifica queste settimane' }))
  expect(onConfirm).toHaveBeenCalledWith([
    { from: '2026-10-05', to: '2026-10-12' },
    { from: '2026-10-19', to: '2026-11-02' },
  ])
})

it('tastiera: Spazio e Invio selezionano con gli stessi modificatori', () => {
  const { week, onConfirm } = open()
  week('2026-10-12').focus()
  fireEvent.keyDown(week('2026-10-12'), { key: ' ' })
  fireEvent.keyDown(week('2026-10-26'), { key: 'Enter', shiftKey: true })
  expect(screen.getByText('3 settimane selezionate')).toBeVisible()
  fireEvent.keyDown(week('2026-11-09'), { key: ' ', metaKey: true })
  expect(screen.getByText('4 settimane selezionate')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Modifica queste settimane' }))
  expect(onConfirm).toHaveBeenCalledWith([
    { from: '2026-10-12', to: '2026-11-02' },
    { from: '2026-11-09', to: '2026-11-16' },
  ])
})

it('conserva la selezione passando a un altro anno e accetta initial singolo', () => {
  const { week, onConfirm } = open(vi.fn(), vi.fn(), { from: '2027-08-23', to: '2027-08-30' })
  expect(screen.getByText('1 settimana selezionata')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Anno successivo' }))
  fireEvent.click(week('2027-08-30'), { shiftKey: true })
  fireEvent.click(screen.getByRole('button', { name: 'Modifica queste settimane' }))
  expect(onConfirm).toHaveBeenCalledWith([{ from: '2027-08-23', to: '2027-09-06' }])
})

it('pulsante ? mostra il tooltip con le scorciatoie adatte alla piattaforma', async () => {
  const originalPlatform = Object.getOwnPropertyDescriptor(navigator, 'platform')
  try {
    Object.defineProperty(navigator, 'platform', { value: 'MacIntel', configurable: true })
    const { unmount } = open()
    const helpBtn = screen.getByRole('button', { name: 'Aiuto sulla selezione' })
    fireEvent.mouseEnter(helpBtn)
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Clic: una settimana · Trascina: più settimane di seguito · ⌘+clic: aggiungi o togli una settimana · ⇧+clic: dall\'ultima scelta a questa',
    )
    unmount()

    Object.defineProperty(navigator, 'platform', { value: 'Win32', configurable: true })
    open()
    const winHelpBtn = screen.getByRole('button', { name: 'Aiuto sulla selezione' })
    fireEvent.mouseEnter(winHelpBtn)
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Clic: una settimana · Trascina: più settimane di seguito · Ctrl+clic: aggiungi o togli una settimana · ⇧+clic: dall\'ultima scelta a questa',
    )
  } finally {
    if (originalPlatform) Object.defineProperty(navigator, 'platform', originalPlatform)
  }
})

it('navigate resta invariato: un clic conferma subito il singolo WeekRange senza footer', () => {
  const onConfirm = vi.fn()
  const { container } = render(
    <WeekRangePopup navigate anchor={anchor} currentDate="2026-10-19" entries={entries} onConfirm={onConfirm} onClose={vi.fn()} />,
  )
  expect(screen.queryByRole('button', { name: 'Modifica queste settimane' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Aiuto sulla selezione' })).not.toBeInTheDocument()
  fireEvent.click(container.querySelector('[data-week="2026-10-12"]')!)
  expect(onConfirm).toHaveBeenCalledWith({ from: '2026-10-12', to: '2026-10-19' })
})

it('Esc e clic fuori chiudono il popup', () => {
  const { onClose } = open()
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(1)
  fireEvent.pointerDown(document.body)
  expect(onClose).toHaveBeenCalledTimes(2)
})

it('Esc chiude il popup anche quando è aperto il suggerimento di una settimana', async () => {
  const { week, onClose } = open()
  fireEvent.mouseEnter(week('2026-10-12'))
  expect(await screen.findByRole('tooltip')).toHaveTextContent('2 ore')
  fireEvent.keyDown(week('2026-10-12'), { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(1)
})
