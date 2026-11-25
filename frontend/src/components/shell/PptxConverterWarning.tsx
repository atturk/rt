import { useCallback, useState } from 'react'

import { useConverters } from '@/api/converters'
import { ConfirmDialog } from '@/components/ui/dialog'

const LIBREOFFICE_DOWNLOAD_URL = 'https://www.libreoffice.org/download/'

/** I file .pptx per cui l'utente ha già confermato "Continua comunque" nella sessione. */
const confirmedPptxFiles = new WeakSet<File>()

export function hasPptxFiles(files: readonly File[]): boolean {
  return files.some((file) => file.name.toLowerCase().endsWith('.pptx'))
}

function unconfirmedPptxFiles(files: readonly File[]): File[] {
  return files.filter((file) => file.name.toLowerCase().endsWith('.pptx') && !confirmedPptxFiles.has(file))
}

function requiredProgramsText(platform: string): string {
  return platform === 'darwin' ? 'LibreOffice (gratuito) o Keynote' : 'LibreOffice (gratuito) o PowerPoint'
}

/**
 * Controlla una volta per sessione se RT può convertire .pptx in immagini; se manca un convertitore
 * chiede conferma prima di procedere con i file .pptx aggiunti.
 */
export function usePptxConverterGuard() {
  const convertersQuery = useConverters()
  const [pending, setPending] = useState<{
    pptxFiles: File[]
    platform: string
    onProceed: () => void
  } | null>(null)

  const pptxInfo = convertersQuery.data?.pptx

  const guardPptxFiles = useCallback(
    (files: File[], onProceed: () => void) => {
      const pendingPptx = unconfirmedPptxFiles(files)
      if (pendingPptx.length === 0 || !pptxInfo || pptxInfo.available) {
        onProceed()
        return
      }

      setPending({
        pptxFiles: pendingPptx,
        platform: pptxInfo.platform,
        onProceed,
      })
    },
    [pptxInfo],
  )

  const warningDialog = (
    <ConfirmDialog
      open={pending !== null}
      title="Nessun convertitore per le slide"
      confirmLabel="Continua comunque"
      cancelLabel="Annulla"
      onCancel={() => setPending(null)}
      onConfirm={() => {
        const current = pending
        setPending(null)
        if (!current) return
        current.pptxFiles.forEach((file) => confirmedPptxFiles.add(file))
        current.onProceed()
      }}
    >
      <div className="flex flex-col gap-2 text-body">
        <p>
          Per vedere le slide come immagini RT ha bisogno di{' '}
          {requiredProgramsText(pending?.platform ?? 'linux')}. Puoi installarlo, oppure esportare
          la presentazione in PDF e caricare il PDF. Senza, RT usa solo il testo delle slide.
        </p>
        <p>
          <a
            href={LIBREOFFICE_DOWNLOAD_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline hover:no-underline"
          >
            Scarica LibreOffice ({LIBREOFFICE_DOWNLOAD_URL})
          </a>
        </p>
      </div>
    </ConfirmDialog>
  )

  return { guardPptxFiles, warningDialog }
}
