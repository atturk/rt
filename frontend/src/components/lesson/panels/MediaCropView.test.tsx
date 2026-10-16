import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import type { LessonImage } from '@/api/images'
import { MediaCropView } from './MediaCropView'

const mockImage: LessonImage = {
  name: 'test-img.png',
  url: '/media/test-img.png',
  source_name: 'Documento1.pdf',
  source: 'material',
  alt_text: 'Documento1.pdf, pagina 5',
  slide_title: '',
  page: 5,
  in_document: true,
  units: ['1.2'],
  in_assets: true,
}

describe('MediaCropView (MS1f)', () => {
  it('mostra titolo, area ritaglio e gestisce Annulla', () => {
    const onClose = vi.fn()
    const onSave = vi.fn()

    render(
      <MediaCropView
        image={mockImage}
        onClose={onClose}
        onSave={onSave}
      />,
    )

    expect(screen.getByText('Pagina 5')).toBeInTheDocument()
    expect(screen.getByTestId('crop-stage')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Riquadro di ritaglio' })).toBeInTheDocument()

    // Clic su Annulla ritaglio
    fireEvent.click(screen.getByLabelText('Annulla ritaglio'))
    expect(onClose).toHaveBeenCalled()
  })

  it('salva come nuova immagine con replace=false', async () => {
    const onSave = vi.fn()

    render(
      <MediaCropView
        image={mockImage}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    )

    fireEvent.click(screen.getByLabelText('Salva come nuova immagine'))
    expect(onSave).toHaveBeenCalledWith(expect.any(Array), false)
  })

  it('reimposta a pagina intera', () => {
    render(
      <MediaCropView
        image={mockImage}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    const box = screen.getByRole('region', { name: 'Riquadro di ritaglio' })
    expect(box).toHaveStyle({ left: '8%', top: '15%' })

    fireEvent.click(screen.getByLabelText('Pagina intera'))
    expect(box).toHaveStyle({ left: '0%', top: '0%', width: '100%', height: '100%' })
  })

  it('mostra popup di conferma per Sostituisci e chiama onSave con replace=true', async () => {
    const onSave = vi.fn()

    render(
      <MediaCropView
        image={mockImage}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    )

    // Clic sull'icona sostituisci pagina
    fireEvent.click(screen.getByLabelText('Sostituisci la pagina con il ritaglio'))

    // Popup aperto
    expect(screen.getByTestId('replace-crop-dialog')).toBeInTheDocument()
    expect(screen.getByText(/È nel testo delle unità 1.2: lì comparirà il ritaglio/)).toBeInTheDocument()

    // Clic su Sostituisci
    const confirmBtn = screen.getByRole('button', { name: 'Sostituisci' })
    fireEvent.click(confirmBtn)

    expect(onSave).toHaveBeenCalledWith(expect.any(Array), true)
  })
})
