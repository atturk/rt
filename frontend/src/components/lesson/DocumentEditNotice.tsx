import { useId, useState } from 'react'

import { type Notice } from '@/api/documentEdit'
import { ConfirmDialog } from '@/components/ui/dialog'

const TEXTS: Record<Notice, { title: string; body: string }> = {
  preview_edit_issues: {
    title: 'Ci sono issue da valutare',
    body:
      "Se modifichi a mano un passaggio segnalato dalla revisione, la sua issue può diventare orfana: resta nell'elenco ma il testo a cui si riferisce non c'è più. Conviene valutare prima le issue.",
  },
  preview_edit_beta: {
    title: 'Funzione beta',
    body:
      "La modifica dell'anteprima è in prova: i timecode potrebbero rompersi. Per modifiche importanti conviene creare il documento, scaricare il Markdown e modificarlo in un editor esterno.",
  },
}

function NoticeText({ notice, checked, onChange }: { notice: Notice; checked: boolean; onChange: (value: boolean) => void }) {
  const id = useId()
  return (
    <section className="flex flex-col gap-1.5" data-notice={notice}>
      <h3 className="font-semibold">{TEXTS[notice].title}</h3>
      <p>{TEXTS[notice].body}</p>
      <label htmlFor={id} className="flex items-center gap-2 text-xs">
        <input id={id} type="checkbox" className="size-4" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        Non mostrare più
      </label>
    </section>
  )
}

/** Avvisi prima di entrare in modifica: uno per voce, ciascuno con "Non mostrare più". */
export function DocumentEditNotice({ notices, onConfirm, onCancel }: { notices: Notice[]; onConfirm: (dismiss: Notice[]) => void; onCancel: () => void }) {
  const [dismiss, setDismiss] = useState<Notice[]>([])
  return (
    <ConfirmDialog open title="Modifica dell'anteprima" confirmLabel="Modifica" onCancel={onCancel} onConfirm={() => onConfirm(dismiss)}>
      <div className="flex flex-col gap-4">
        {notices.map((n) => (
          <NoticeText
            key={n}
            notice={n}
            checked={dismiss.includes(n)}
            onChange={(value) => setDismiss((cur) => (value ? [...cur, n] : cur.filter((x) => x !== n)))}
          />
        ))}
      </div>
    </ConfirmDialog>
  )
}
