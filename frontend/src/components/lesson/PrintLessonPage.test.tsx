import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, it, vi } from 'vitest'

import { RT_SITE_URL, rtSiteLabel } from '@/lib/rtSite'

import { PrintLessonPage } from './PrintLessonPage'

const mockLesson: {
  id: number
  materia: string
  titolo: string
  data: string
  docente?: string | null
} = { id: 1, materia: 'FISIOLOGIA', titolo: 'Acidosi', data: '2026-10-02' }

vi.mock('@/api/hooks', () => ({
  useLesson: () => ({ data: { ...mockLesson } }),
  useLessonDocument: () => ({
    data: {
      html: '<h3 data-unit-id="u1">Titolo</h3><p data-unit-timecode="u1">00:22</p><p>Testo</p>',
      sections: [{ unit_id: 'u1', start_formatted: '00:22' }],
    },
  }),
}))

beforeEach(() => {
  delete mockLesson.docente
})

it('il timecode compare una volta sola, accanto al titolo', async () => {
  const { container } = render(
    <MemoryRouter initialEntries={['/stampa/1']}>
      <Routes><Route path="/stampa/:lessonId" element={<PrintLessonPage />} /></Routes>
    </MemoryRouter>,
  )
  await waitFor(() => expect(container.querySelector('.print-timecode')).not.toBeNull())
  expect(screen.getByText('Testo')).toBeInTheDocument()
  expect(container.querySelector('[data-unit-timecode]')).toBeNull()
  const content = container.querySelector('.print-content')!
  expect(content.textContent!.match(/00:22/g)).toHaveLength(1)
  expect(container.querySelector('.print-timecode')).toHaveTextContent('00:22')
})

it('definisce gli stili per elenchi puntati, numerati, rientro e annidati nel tag style', () => {
  const { container } = render(
    <MemoryRouter initialEntries={['/stampa/1']}>
      <Routes><Route path="/stampa/:lessonId" element={<PrintLessonPage />} /></Routes>
    </MemoryRouter>,
  )
  const styleText = container.querySelector('style')?.textContent ?? ''
  expect(styleText).toContain('.print-page ul')
  expect(styleText).toContain('list-style: disc')
  expect(styleText).toContain('.print-page ol')
  expect(styleText).toContain('list-style: decimal')
  expect(styleText).toContain('padding-left: 1.4em')
  expect(styleText).toContain('list-style: circle')
})

it('il QR per il timbro sta nel contenitore fuori flusso [data-rt-stamp] e il titolo è a tutta larghezza', async () => {
  const { container } = render(
    <MemoryRouter initialEntries={['/stampa/1']}>
      <Routes><Route path="/stampa/:lessonId" element={<PrintLessonPage />} /></Routes>
    </MemoryRouter>,
  )
  const qr = screen.getByTestId('rt-site-qr')
  expect(qr).toHaveAttribute('href', RT_SITE_URL)
  expect(qr).toHaveTextContent('Rielaborato con RT')
  expect(qr).toHaveTextContent(rtSiteLabel())
  const stamp = container.querySelector('[data-rt-stamp]')
  expect(stamp).not.toBeNull()
  expect(stamp).toContainElement(qr)
  expect(container.querySelector('.print-head')).toBeNull()
  const styleText = container.querySelector('style')?.textContent ?? ''
  expect(styleText).toContain('.print-rt-stamp')
  expect(styleText).toContain('text-wrap: wrap')
  // Lascia finire l'impaginazione: un lavoro di React rimasto in coda dopo la fine del file
  // scatta senza jsdom («window is not defined») nel file di test successivo.
  await waitFor(() => expect(document.body.dataset.ready).toBe('1'))
})

it('mostra i metadati con docente quando presente e li omette quando assente', async () => {
  mockLesson.docente = 'Prof. Rossi'
  const { container, unmount } = render(
    <MemoryRouter initialEntries={['/stampa/1']}>
      <Routes><Route path="/stampa/:lessonId" element={<PrintLessonPage />} /></Routes>
    </MemoryRouter>,
  )
  expect(container.querySelector('.print-header')).toHaveTextContent('Fisiologia · Prof. Rossi · 2 ott')
  await waitFor(() => expect(document.body.dataset.ready).toBe('1'))
  unmount()

  delete mockLesson.docente
  const second = render(
    <MemoryRouter initialEntries={['/stampa/1']}>
      <Routes><Route path="/stampa/:lessonId" element={<PrintLessonPage />} /></Routes>
    </MemoryRouter>,
  )
  expect(second.container.querySelector('.print-header')).toHaveTextContent('Fisiologia · 2 ott')
  await waitFor(() => expect(document.body.dataset.ready).toBe('1'))
})
