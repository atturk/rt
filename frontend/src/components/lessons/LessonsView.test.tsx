import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { LessonsHeaderActions, LessonsList } from './LessonsView'
import type { Lesson } from '@/lib/format'
import type { LessonsPrefs } from '@/lib/lessonsPage'

afterEach(() => {
  cleanup()
})

const sampleLesson = (id: number, titolo = `Lezione ${id}`): Lesson => ({
  id,
  titolo,
  folder_name: `f${id}`,
  data: '2026-10-02',
  ora: '09:00',
  materia: 'FISIOLOGIA',
  argomenti: '',
  docente: 'Rossi',
  phases: { build: 'VALID' },
  pending_issues: 0,
  cost_usd: 0.1,
  unit_count: 5,
  duration_seconds: 1200,
  recall_questions: 10,
  recall_pending: 2,
  study_ignored: 0,
  study_learned: 0,
  study_learning: 0,
  path: '',
  state: 'completato',
})

function renderHeader(prefs: LessonsPrefs, onPrefs = vi.fn()) {
  const qc = new QueryClient()
  return {
    onPrefs,
    ...render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <LessonsHeaderActions
            prefs={prefs}
            onPrefs={onPrefs}
            query=""
            onQuery={() => {}}
            selecting={false}
            onSelecting={() => {}}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  }
}

function renderList(grouping: LessonsPrefs['group'], groups = [{ key: 'tutte', label: 'Tutte le lezioni', lessons: [sampleLesson(1), sampleLesson(2)] }]) {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <LessonsList
          groups={groups}
          grouping={grouping}
          running={new Set()}
          selecting={false}
          selected={new Set()}
          onSelected={() => {}}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LessonsView - raggruppamento', () => {
  it('giro Per data → Per mese → nessuno → Per data', () => {
    // 1. Per data attivo -> clic passa a Per mese
    const h1 = renderHeader({ group: 'data', sort: 'recenti' })
    const dateBtn1 = screen.getByRole('button', { name: 'Per data' })
    expect(dateBtn1).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(dateBtn1)
    expect(h1.onPrefs).toHaveBeenCalledWith({ group: 'mese' })
    cleanup()

    // 2. Per mese attivo -> clic passa a nessuno
    const h2 = renderHeader({ group: 'mese', sort: 'recenti' })
    const dateBtn2 = screen.getByRole('button', { name: 'Per mese' })
    expect(dateBtn2).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(dateBtn2)
    expect(h2.onPrefs).toHaveBeenCalledWith({ group: 'nessuno' })
    cleanup()

    // 3. nessuno attivo -> clic passa a Per data
    const h3 = renderHeader({ group: 'nessuno', sort: 'recenti' })
    const dateBtn3 = screen.getByRole('button', { name: 'Per data' })
    expect(dateBtn3).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(dateBtn3)
    expect(h3.onPrefs).toHaveBeenCalledWith({ group: 'data' })
  })

  it('un clic sul raggruppamento attivo lo spegne e nessuno è attivo', () => {
    // Materia attivo -> clic spegne a nessuno
    const hMat = renderHeader({ group: 'materia', sort: 'recenti' })
    const matBtn = screen.getByRole('button', { name: 'Per materia' })
    expect(matBtn).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(matBtn)
    expect(hMat.onPrefs).toHaveBeenCalledWith({ group: 'nessuno' })
    cleanup()

    // Docente attivo -> clic spegne a nessuno
    const hDoc = renderHeader({ group: 'docente', sort: 'recenti' })
    const docBtn = screen.getByRole('button', { name: 'Per docente' })
    expect(docBtn).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(docBtn)
    expect(hDoc.onPrefs).toHaveBeenCalledWith({ group: 'nessuno' })
    cleanup()

    // Con nessuno: nessun pulsante è attivo (aria-pressed === false)
    renderHeader({ group: 'nessuno', sort: 'recenti' })
    expect(screen.getByRole('button', { name: 'Per data' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Per materia' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Per docente' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('con nessuno l\'elenco è unico, senza intestazioni né sfondo', () => {
    renderList('nessuno')
    // Nessuna intestazione di gruppo (h2)
    expect(screen.queryByRole('heading', { level: 2 })).toBeNull()
    const section = screen.getByTestId('lesson-group')
    expect(section.style.background).toBe('')
    // Le lezioni sono presenti
    expect(screen.getByRole('link', { name: 'Lezione 1' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Lezione 2' })).toBeInTheDocument()
  })

  it('con materia l\'elenco mostra l\'intestazione di gruppo', () => {
    renderList('materia', [{ key: 'FISIOLOGIA', label: 'FISIOLOGIA', lessons: [sampleLesson(1)] }])
    expect(screen.getByRole('heading', { level: 2, name: 'Fisiologia' })).toBeInTheDocument()
  })
})
