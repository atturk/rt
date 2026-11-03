import { useState } from 'react'
import { Modal } from '@/components/ui/modal'
import { Button } from '@/components/ui/button'

export function IrlenWarningModal({
  open,
  onClose,
  onDismiss,
}: {
  open: boolean
  onClose: () => void
  onDismiss: (dontShowAgain: boolean) => void
}) {
  const [dontShowAgain, setDontShowAgain] = useState(false)
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Modalità Irlen"
      testId="irlen-warning-modal"
    >
      <p className="mt-2 text-body">
        Con la modalità Irlen alcuni colori delle evidenziazioni potrebbero vedersi poco.
      </p>
      <label className="mt-4 flex items-center gap-2 text-meta text-muted-foreground cursor-pointer">
        <input
          type="checkbox"
          checked={dontShowAgain}
          onChange={(e) => setDontShowAgain(e.target.checked)}
          className="rounded border-border"
        />
        <span>Non mostrare più</span>
      </label>
      <div className="mt-5 flex justify-end">
        <Button
          onClick={() => {
            onDismiss(dontShowAgain)
            onClose()
          }}
        >
          OK
        </Button>
      </div>
    </Modal>
  )
}
