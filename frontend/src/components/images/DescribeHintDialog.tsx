import { useState } from 'react'

import { ConfirmDialog } from '@/components/ui/dialog'

/** Con la lettura "decision" descrivere non serve per collocare: lo si dice una volta. */
export function DescribeHintDialog({ open, onConfirm, onCancel }: { open: boolean; onConfirm: (hide: boolean) => void; onCancel: () => void }) {
  const [hide, setHide] = useState(false)
  return (
    <ConfirmDialog open={open} title="Descrivi" confirmLabel="OK" onConfirm={() => onConfirm(hide)} onCancel={onCancel}>
      <p>Il modello decisionale assegna già le immagini: non serve descriverle.</p>
      <label className="mt-3 flex items-center gap-2 text-meta">
        <input type="checkbox" checked={hide} onChange={(e) => setHide(e.target.checked)} />
        Non mostrare più
      </label>
    </ConfirmDialog>
  )
}
