import type { Schemas } from '@/api/client'
import { ConfirmDialog } from '@/components/ui/dialog'

/** Avvisi della stessa fase build, sia da Dettagli sia da Verifica. */
export function BuildConfirmDialog({ open, warnings, onCancel, onConfirm }: {
  open: boolean; warnings: Schemas['PhaseWarning'][]; onCancel: () => void; onConfirm: () => void
}) {
  return <ConfirmDialog open={open} title="Creare il documento finale?" confirmLabel="Crea il documento comunque" onCancel={onCancel} onConfirm={onConfirm}>
    <p>Il documento finale sarà uguale all'anteprima che vedi ora. Prima di confermarlo, controlla:</p>
    <ul className="mt-2 list-disc pl-5" data-testid="build-confirm-warnings">
      {warnings.map(w => <li key={w.code}>{w.message}</li>)}
    </ul>
  </ConfirmDialog>
}
