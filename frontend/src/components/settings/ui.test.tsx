import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { IconButton } from '@/components/ui/icon-button'
import { SettingsDisclosure, SettingsGroup, SettingsMatrix, SettingsPage, SettingsRow, SettingsSwitch } from './ui'
import { useAutoSave } from './useAutoSave'
import { Type, Layers } from 'lucide-react'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('Tooltip portale in SettingsGroup / SettingsRow', () => {
  it('il testo del tooltip di una riga sta in document.body fuori dal gruppo e mai dentro overflow-hidden', () => {
    vi.useFakeTimers()
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))

    render(
      <SettingsPage title="Lavorazione" description="Descrizione della pagina.">
        <SettingsGroup id="grp-test" title="Gruppo di prova">
          <SettingsRow
            label="Prima riga"
            info="Spiegazione dettagliata della prima riga"
            control={<input aria-label="Prima riga" />}
          />
          <SettingsRow
            label="Ultima riga"
            info="Spiegazione dettagliata dell’ultima riga"
            control={<input aria-label="Ultima riga" />}
          />
        </SettingsGroup>
      </SettingsPage>,
    )

    const group = screen.getByRole('region', { name: 'Gruppo di prova' })
    const firstInfo = screen.getByRole('button', { name: 'Informazioni su Prima riga' })
    const lastInfo = screen.getByRole('button', { name: 'Informazioni su Ultima riga' })

    // Nessun overflow-hidden sul riquadro del gruppo
    expect(group.innerHTML).not.toMatch(/overflow-hidden/)

    // Apri tooltip sulla prima riga
    fireEvent.mouseEnter(firstInfo)
    act(() => { vi.advanceTimersByTime(600) })

    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toHaveTextContent('Spiegazione dettagliata della prima riga')
    expect(tooltip.parentElement).toBe(document.body)
    expect(group.contains(tooltip)).toBe(false)

    // Verifica che nessun antenato del tooltip abbia overflow nascosto
    let el: HTMLElement | null = tooltip.parentElement
    while (el) {
      const style = getComputedStyle(el)
      expect(style.overflow).not.toBe('hidden')
      expect(style.overflowX).not.toBe('hidden')
      expect(style.overflowY).not.toBe('hidden')
      el = el.parentElement
    }

    // Anche sull'ultima riga resta in document.body fuori dal gruppo
    fireEvent.mouseLeave(firstInfo)
    fireEvent.mouseEnter(lastInfo)
    const lastTooltip = screen.getByRole('tooltip')
    expect(lastTooltip).toHaveTextContent('Spiegazione dettagliata dell’ultima riga')
    expect(lastTooltip.parentElement).toBe(document.body)
    expect(group.contains(lastTooltip)).toBe(false)
  })
})

describe('SettingsSwitch e SettingsDisclosure', () => {
  it('SettingsSwitch rende un switch accessibile e SettingsDisclosure espande e chiude', () => {
    const onToggle = vi.fn()
    render(
      <SettingsGroup title="Sezione">
        <SettingsSwitch id="sw-test" label="Opzione attiva" checked={true} onChange={onToggle} />
        <SettingsDisclosure label="Regola avanzata" summary="3 voti">
          <p>Contenuto nascosto</p>
        </SettingsDisclosure>
      </SettingsGroup>,
    )

    const sw = screen.getByRole('switch', { name: 'Opzione attiva' })
    expect(sw).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(sw)
    expect(onToggle).toHaveBeenCalledWith(false)

    const btn = screen.getByRole('button', { name: /Regola avanzata/ })
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Contenuto nascosto')).toBeNull()
    fireEvent.click(btn)
    expect(btn).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Contenuto nascosto')).toBeVisible()
  })
})

describe('SettingsMatrix', () => {
  it('mostra l’intestazione una volta sola e tooltip in document.body per le icone', () => {
    vi.useFakeTimers()
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))

    render(
      <SettingsGroup title="Fonti">
        <SettingsMatrix
          columnGroups={[
            { id: 'extract', label: 'Cosa usare', columns: [{ key: 'testo', label: 'Testo' }] },
            { id: 'use', label: 'Come usarla', columns: [{ key: 'contesto', label: 'Contesto' }] },
          ]}
          rows={[
            {
              id: 'slide',
              label: 'Slide',
              testId: 'row-slide',
              cells: {
                extract: <IconButton icon={Type} label="Testo" onClick={() => {}} />,
                use: <IconButton icon={Layers} label="Contesto: arricchisce la fonte principale" onClick={() => {}} />,
              },
            },
            {
              id: 'testo',
              label: 'Testi',
              testId: 'row-testo',
              cells: {
                extract: <IconButton icon={Type} label="Testo" onClick={() => {}} />,
                use: <IconButton icon={Layers} label="Contesto: arricchisce la fonte principale" onClick={() => {}} />,
              },
            },
          ]}
        />
      </SettingsGroup>,
    )

    expect(screen.getAllByText('Cosa usare')).toHaveLength(1)
    expect(screen.getAllByText('Come usarla')).toHaveLength(1)
    const icon = screen.getAllByRole('button', { name: 'Contesto: arricchisce la fonte principale' })[0]
    fireEvent.mouseEnter(icon)
    act(() => { vi.advanceTimersByTime(600) })
    const tooltip = screen.getByRole('tooltip')
    expect(tooltip.parentElement).toBe(document.body)
  })
})

describe('useAutoSave', () => {
  function AutoSaveHarness({
    mutate,
    delay = 600,
    enabled = true,
  }: {
    mutate: (v: string, opts?: { onSuccess?: () => void; onError?: (e: unknown) => void }) => void
    delay?: number
    enabled?: boolean
  }) {
    const [val, setVal] = useState('iniziale')
    const save = useAutoSave({ mutate }, val, { delay, enabled, initial: 'iniziale' })
    return (
      <SettingsRow
        label="Campo"
        htmlFor="campo"
        status={save}
        control={
          <input
            id="campo"
            value={val}
            onChange={(e) => setVal(e.target.value)}
            onBlur={save.flush}
          />
        }
      />
    )
  }

  it('salva dopo 600 ms senza digitare, mostra Salvato e sparisce dopo 1,5 s', () => {
    vi.useFakeTimers()
    const mutate = vi.fn((_v: string, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.())
    render(<AutoSaveHarness mutate={mutate} />)

    expect(mutate).not.toHaveBeenCalled()
    const input = screen.getByLabelText('Campo')
    fireEvent.change(input, { target: { value: 'nuovo' } })
    act(() => { vi.advanceTimersByTime(599) })
    expect(mutate).not.toHaveBeenCalled()

    act(() => { vi.advanceTimersByTime(1) })
    expect(mutate).toHaveBeenCalledTimes(1)
    expect(mutate).toHaveBeenCalledWith('nuovo', expect.any(Object))
    expect(screen.getByRole('status')).toHaveTextContent('Salvato')

    act(() => { vi.advanceTimersByTime(1500) })
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('salva subito al blur senza aspettare i 600 ms', () => {
    vi.useFakeTimers()
    const mutate = vi.fn((_v: string, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.())
    render(<AutoSaveHarness mutate={mutate} />)

    const input = screen.getByLabelText('Campo')
    fireEvent.change(input, { target: { value: 'al-blur' } })
    fireEvent.blur(input)
    expect(mutate).toHaveBeenCalledTimes(1)
    expect(mutate).toHaveBeenCalledWith('al-blur', expect.any(Object))
  })

  it('mostra errore in rosso con Riprova e ritenta al clic', () => {
    vi.useFakeTimers()
    let shouldFail = true
    const mutate = vi.fn((_v: string, opts?: { onSuccess?: () => void; onError?: (e: unknown) => void }) => {
      if (shouldFail) opts?.onError?.(new Error('Rete assente'))
      else opts?.onSuccess?.()
    })
    render(<AutoSaveHarness mutate={mutate} />)

    const input = screen.getByLabelText('Campo')
    fireEvent.change(input, { target: { value: 'test' } })
    fireEvent.blur(input)

    expect(screen.getByRole('alert')).toHaveTextContent('Rete assente')
    const retry = screen.getByRole('button', { name: 'Riprova' })
    shouldFail = false
    fireEvent.click(retry)
    expect(mutate).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('status')).toHaveTextContent('Salvato')
  })
})
