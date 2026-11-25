import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useConverters } from '@/api/converters'
import { api } from '@/api/client'
import { SourcesSection } from '@/components/lesson/panels/SourcesSection'
import { NewLessonDialog } from '@/components/lessons/NewLessonDialog'
import { usePptxConverterGuard } from './PptxConverterWarning'

function GuardHarness({ onProceed }: { onProceed: (files: File[]) => void }) {
  const { data } = useConverters()
  const { guardPptxFiles, warningDialog } = usePptxConverterGuard()
  return (
    <div data-converters-ready={data ? 'yes' : 'no'}>
      <button
        type="button"
        onClick={() => void guardPptxFiles([new File(['pdf'], 'slide.pdf')], () => onProceed([]))}
      >
        Aggiungi PDF
      </button>
      <button
        type="button"
        onClick={() => {
          const f = new File(['pptx'], 'presentazione.pptx')
          void guardPptxFiles([f], () => onProceed([f]))
        }}
      >
        Aggiungi PPTX
      </button>
      {warningDialog}
    </div>
  )
}

function wrap(ui: React.ReactElement, client?: QueryClient) {
  const qc =
    client ??
    new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PptxConverterWarning', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('mostra il dialogo solo per .pptx quando available è false e interroga l’API una sola volta per sessione', async () => {
    const getSpy = vi.spyOn(api, 'GET').mockImplementation((path: string) => {
      if (path === '/api/v1/system/converters') {
        return Promise.resolve({
          data: { pptx: { available: false, methods: [], platform: 'darwin' } },
          error: undefined,
          response: new Response('{}', { status: 200 }),
        } as never)
      }
      return Promise.resolve({ data: {}, response: new Response('{}', { status: 200 }) } as never)
    })

    const onProceed = vi.fn()
    const { container } = wrap(<GuardHarness onProceed={onProceed} />)

    await waitFor(() => expect(container.querySelector('[data-converters-ready="yes"]')).not.toBeNull())
    expect(getSpy).toHaveBeenCalledTimes(1)

    // Un .pdf non apre l'avviso
    fireEvent.click(screen.getByRole('button', { name: 'Aggiungi PDF' }))
    expect(onProceed).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/Per vedere le slide come immagini RT ha bisogno di/i)).not.toBeInTheDocument()

    // Un .pptx apre l'avviso su macOS (LibreOffice o Keynote + link)
    fireEvent.click(screen.getByRole('button', { name: 'Aggiungi PPTX' }))
    expect(screen.getByText(/LibreOffice \(gratuito\) o Keynote/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /LibreOffice/i })).toHaveAttribute(
      'href',
      'https://www.libreoffice.org/download/',
    )
    expect(onProceed).toHaveBeenCalledTimes(1)

    // Annulla non aggiunge i file
    fireEvent.click(screen.getByRole('button', { name: 'Annulla' }))
    expect(screen.queryByText(/Per vedere le slide come immagini RT ha bisogno di/i)).not.toBeInTheDocument()
    expect(onProceed).toHaveBeenCalledTimes(1)

    // Riaprendo e cliccando "Continua comunque" procede senza interrogare nuovamente /converters
    fireEvent.click(screen.getByRole('button', { name: 'Aggiungi PPTX' }))
    fireEvent.click(screen.getByRole('button', { name: 'Continua comunque' }))
    expect(onProceed).toHaveBeenCalledTimes(2)
    expect(getSpy).toHaveBeenCalledTimes(1)
  })

  it('non mostra l’avviso se available è true e su Windows cita PowerPoint quando manca', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: { pptx: { available: true, methods: ['LibreOffice'], platform: 'darwin' } },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)

    const onProceed = vi.fn()
    const first = wrap(<GuardHarness onProceed={onProceed} />)
    await waitFor(() => expect(first.container.querySelector('[data-converters-ready="yes"]')).not.toBeNull())
    fireEvent.click(screen.getByRole('button', { name: 'Aggiungi PPTX' }))
    expect(onProceed).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/Per vedere le slide come immagini/i)).not.toBeInTheDocument()
    first.unmount()

    vi.spyOn(api, 'GET').mockResolvedValue({
      data: { pptx: { available: false, methods: [], platform: 'win32' } },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)
    const second = wrap(<GuardHarness onProceed={onProceed} />)
    await waitFor(() => expect(second.container.querySelector('[data-converters-ready="yes"]')).not.toBeNull())
    fireEvent.click(screen.getByRole('button', { name: 'Aggiungi PPTX' }))
    expect(screen.getByText(/LibreOffice \(gratuito\) o PowerPoint/i)).toBeInTheDocument()
  })

  it('mostra l’avviso in Nuova lezione e in Aggiungi materiale per .pptx non supportato', async () => {
    vi.spyOn(api, 'GET').mockImplementation((path: string) => {
      if (path === '/api/v1/system/converters') {
        return Promise.resolve({
          data: { pptx: { available: false, methods: [], platform: 'darwin' } },
          error: undefined,
          response: new Response('{}', { status: 200 }),
        } as never)
      }
      if (path === '/api/v1/lessons/42/sources') {
        return Promise.resolve({
          data: { sources: [], has_unused_sources: false, can_undo: false, ultimo_aggiornamento: null },
          error: undefined,
          response: new Response('{}', { status: 200 }),
        } as never)
      }
      return Promise.resolve({ data: [], error: undefined, response: new Response('[]', { status: 200 }) } as never)
    })

    const { unmount } = wrap(<NewLessonDialog open onClose={vi.fn()} />)
    await waitFor(() => expect(api.GET).toHaveBeenCalledWith('/api/v1/system/converters'))
    await new Promise((r) => setTimeout(r, 0))
    const pptx = new File(['slide'], 'lezione.pptx')
    fireEvent.change(screen.getByLabelText('Audio o pacchetto della lezione'), { target: { files: [pptx] } })
    expect(screen.getByRole('button', { name: 'Continua comunque' })).toBeInTheDocument()
    expect(screen.queryByText('lezione.pptx')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Continua comunque' }))
    expect(screen.getByText('lezione.pptx')).toBeInTheDocument()
    unmount()

    wrap(<SourcesSection lessonId={42} />)
    await waitFor(() => expect(api.GET).toHaveBeenCalledWith('/api/v1/system/converters'))
    await new Promise((r) => setTimeout(r, 0))
    const input = document.querySelector('input[accept*=".pptx"]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [new File(['slide'], 'altro.pptx')] } })
    expect(screen.getByRole('button', { name: 'Continua comunque' })).toBeInTheDocument()
  })
})
