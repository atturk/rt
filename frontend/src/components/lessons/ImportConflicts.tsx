import { useState } from 'react'

import { errorMessage } from '@/api/client'
import type { ImportedLessonInfo, ZipImportDecision, ZipImportItem } from '@/api/jobs'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

type Choice = 'replace' | 'keep' | 'skip'

/** Chiave stabile di un conflitto: lo ZIP caricato e, per un gruppo, la lezione al suo interno. */
const keyOf = (item: ZipImportItem) => `${item.archive ?? item.file}\u0000${item.member ?? ''}`

function when(info?: ImportedLessonInfo) {
  if (!info) return ''
  const [y, m, d] = info.data.split('-')
  const day = y && m && d ? `${d}/${m}/${y}` : info.data
  return [info.materia, day, info.ora].filter(Boolean).join(' · ')
}

function describe(info?: ImportedLessonInfo) {
  if (!info) return ''
  return info.titolo && info.titolo !== info.folder_name ? info.titolo : info.argomenti || info.folder_name
}

/** Salva sul computer lo ZIP completo (stato dello studio compreso) di una lezione. Il file si
 * scarica per intero prima di proseguire: la lezione viene rimpiazzata solo dopo. */
async function downloadLessonCopy(lessonId: number, fallbackName: string) {
  const response = await fetch(`/api/v1/lessons/${lessonId}/export?format=zip&scope=all&study=1`, { credentials: 'same-origin' })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(body?.error?.message ?? `Copia non riuscita (${response.status})`)
  }
  const encoded = /filename\*=UTF-8''([^;]+)/.exec(response.headers.get('content-disposition') ?? '')?.[1]
  const link = document.createElement('a')
  link.href = URL.createObjectURL(await response.blob())
  link.download = encoded ? decodeURIComponent(encoded) : `${fallbackName}.zip`
  link.click()
  URL.revokeObjectURL(link.href)
}

/** Lezioni del pacchetto che l'utente ha già (stessa data, materia e ora): per ognuna si
 * sceglie se rimpiazzare la propria, tenerle entrambe o non importarla. Prima di rimpiazzare
 * si offre di scaricare una copia della lezione attuale. */
export function ImportConflicts({
  items,
  files,
  onSubmit,
}: {
  items: ZipImportItem[]
  /** Gli ZIP caricati: quelli con una scelta si rimandano con le decisioni. */
  files: File[]
  onSubmit: (files: File[], decisions: ZipImportDecision[]) => void
}) {
  const [choices, setChoices] = useState<Record<string, Choice>>({})
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const choiceOf = (item: ZipImportItem): Choice => choices[keyOf(item)] ?? 'skip'
  const replacing = items.filter((item) => choiceOf(item) === 'replace' && item.existing?.lesson_id != null)
  const decisions: ZipImportDecision[] = items.flatMap((item) => {
    const choice = choiceOf(item)
    if (choice === 'skip') return []
    return [{
      file: item.archive ?? item.file,
      ...(item.member ? { member: item.member } : {}),
      action: choice,
      ...(choice === 'replace' ? { lesson_id: item.existing?.lesson_id } : {}),
    }]
  })
  const toSend = files.filter((file) => decisions.some((d) => d.file === file.name))
  const missing = decisions.length > 0 && toSend.length === 0

  function send() {
    setConfirming(false)
    onSubmit(toSend, decisions)
  }

  async function saveCopiesAndSend() {
    setSaving(true)
    setError(null)
    try {
      for (const item of replacing) {
        await downloadLessonCopy(item.existing!.lesson_id!, item.existing!.folder_name)
      }
      send()
    } catch (reason) {
      setError(`${errorMessage(reason)}. Nessuna lezione è stata rimpiazzata.`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="my-3 rounded-md border border-input p-3" aria-label="Lezioni già presenti" data-testid="import-conflicts">
      <p className="text-meta font-semibold">
        {items.length === 1 ? 'Questa lezione ce l’hai già' : `${items.length} lezioni ce le hai già`}
      </p>
      <p className="mb-2 text-meta text-muted-foreground">
        Stessa materia, stesso giorno e stessa ora, ma fonti diverse. Scegli cosa fare. Se rimpiazzi,
        la tua lezione viene sostituita per intero: file, scaletta e stato dello studio.
      </p>
      <ul className="space-y-3">
        {items.map((item) => {
          const key = keyOf(item)
          const name = `conflict-${key}`
          return (
            <li key={key} className="text-meta">
              <p className="font-medium">{when(item.existing)}</p>
              <p className="text-muted-foreground">
                La tua: «{describe(item.existing)}» · Nel pacchetto: «{describe(item.incoming)}» ({item.file})
              </p>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1" role="radiogroup" aria-label={`Cosa fare con ${item.file}`}>
                <label className="flex items-center gap-1.5">
                  <input type="radio" name={name} className="size-4 accent-current" checked={choiceOf(item) === 'replace'}
                    onChange={() => setChoices((c) => ({ ...c, [key]: 'replace' }))} />
                  Rimpiazza la mia
                </label>
                {item.can_keep_both && (
                  <label className="flex items-center gap-1.5">
                    <input type="radio" name={name} className="size-4 accent-current" checked={choiceOf(item) === 'keep'}
                      onChange={() => setChoices((c) => ({ ...c, [key]: 'keep' }))} />
                    Tienile entrambe
                  </label>
                )}
                <label className="flex items-center gap-1.5">
                  <input type="radio" name={name} className="size-4 accent-current" checked={choiceOf(item) === 'skip'}
                    onChange={() => setChoices((c) => ({ ...c, [key]: 'skip' }))} />
                  Non importarla
                </label>
              </div>
            </li>
          )
        })}
      </ul>

      {missing && (
        <Alert tone="warning" className="mt-3">
          Il pacchetto non è più disponibile in questa finestra: trascinalo di nuovo per scegliere.
        </Alert>
      )}
      {error && <Alert tone="danger" className="mt-3">{error}</Alert>}

      {confirming ? (
        <div className="mt-3 rounded-md bg-muted p-3 text-meta" role="alertdialog" aria-label="Copia prima di rimpiazzare">
          <p className="font-medium">
            Prima di rimpiazzare vuoi scaricare una copia {replacing.length === 1 ? 'della tua lezione' : 'delle tue lezioni'}?
          </p>
          <p className="mb-2 text-muted-foreground">
            È lo ZIP completo, stato dello studio compreso: se poi cambi idea lo reimporti da qui.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" disabled={saving} onClick={() => void saveCopiesAndSend()}>
              {saving ? 'Scarico la copia…' : 'Scarica la copia e rimpiazza'}
            </Button>
            <Button type="button" size="sm" variant="outline" disabled={saving} onClick={send}>
              Rimpiazza senza copia
            </Button>
            <Button type="button" size="sm" variant="ghost" disabled={saving} onClick={() => setConfirming(false)}>
              Indietro
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-3">
          <Button type="button" size="sm" disabled={decisions.length === 0 || missing}
            onClick={() => (replacing.length > 0 ? setConfirming(true) : send())}>
            Continua
          </Button>
        </div>
      )}
    </section>
  )
}
