import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { AlertTriangle, Download, Upload } from 'lucide-react'
import { calendarKeys, calendarTransferApi } from '@/api/calendar'
import { subjectsKeys } from '@/api/subjects'
import { errorMessage } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'

export function CalendarScheduleSettings({ onError }: { onError: (error: string | null) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<{ name: string; data: Record<string, unknown> } | null>(null)
  const [period, setPeriod] = useState(false)
  const [from, setFrom] = useState(''), [to, setTo] = useState('')
  const [exporting, setExporting] = useState(false)
  const client = useQueryClient()
  const valid = !period || !!from && !!to && from <= to
  const preview = useQuery({ queryKey: ['calendar-import-preview', file?.data, period, from, to],
    queryFn: () => calendarTransferApi.import(file!.data, true, period ? from : undefined, period ? to : undefined),
    enabled: !!file && valid, retry: false, staleTime: 0,
  })
  const mutation = useMutation({ mutationFn: () => calendarTransferApi.import(file!.data, false, period ? from : undefined, period ? to : undefined),
    onSuccess: () => {
      setFile(null)
      void client.invalidateQueries({ queryKey: calendarKeys.all })
      void client.invalidateQueries({ queryKey: subjectsKeys.all })
    },
  })
  async function exportFile() {
    setExporting(true); onError(null)
    try {
      const data = await calendarTransferApi.export()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const now = new Date()
      const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
      link.href = url; link.download = `rt-orario-${date}.rtcal`; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) { onError(errorMessage(error)) }
    finally { setExporting(false) }
  }
  const conflicts = preview.data?.conflicts ?? 0
  return <>
    <div className="flex items-center gap-1">
      <span className="mr-auto text-body font-medium">Orario del calendario</span>
      <IconButton icon={Download} label="Esporta l’orario" disabled={exporting} onClick={() => void exportFile()} />
      <IconButton icon={Upload} label="Importa un orario" onClick={() => input.current?.click()} />
      <input ref={input} type="file" accept=".rtcal,.json" aria-label="File dell’orario" className="hidden" onChange={event => {
        const chosen = event.target.files?.[0]
        event.target.value = ''
        if (!chosen) return
        onError(null); mutation.reset()
        if (chosen.size > 1024 * 1024) { onError('Il file supera 1 MB.'); return }
        void chosen.text().then(text => {
          const data: unknown = JSON.parse(text)
          if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('File non valido')
          setPeriod(false); setFrom(''); setTo('')
          setFile({ name: chosen.name, data: data as Record<string, unknown> })
        }).catch(() => onError('Il file non contiene un orario valido.'))
      }} />
    </div>
    <Modal title="Importa orario" open={!!file} onClose={() => { if (!mutation.isPending) setFile(null) }}>
      <div className="mt-4 flex flex-col gap-3">
        <p className="text-sm">{file?.name}{preview.data ? ` · ${preview.data.subjects} materie` : ''}</p>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={period} onChange={event => setPeriod(event.target.checked)} disabled={mutation.isPending} />Solo in un periodo</label>
        {period && <div className="grid grid-cols-2 gap-2">
          <label className="text-sm">Dal<Input type="date" value={from} onChange={event => setFrom(event.target.value)} disabled={mutation.isPending} /></label>
          <label className="text-sm">Al<Input type="date" value={to} min={from} onChange={event => setTo(event.target.value)} disabled={mutation.isPending} /></label>
        </div>}
        {preview.isError && <Alert tone="danger">{errorMessage(preview.error)}</Alert>}
        {mutation.isError && <Alert tone="danger">{errorMessage(mutation.error)}</Alert>}
        {conflicts > 0 && <div className="flex items-center gap-2 text-sm text-danger"><AlertTriangle aria-hidden className="size-5 shrink-0" /><span>Sostituisce l’orario attuale{period && from && to ? ` dal ${from} al ${to}` : ''}</span></div>}
        <div className="flex justify-end gap-2"><Button disabled={mutation.isPending} onClick={() => setFile(null)}>Annulla</Button>
          <Button disabled={!valid || !preview.data || preview.isFetching || preview.isError || mutation.isPending} className={conflicts > 0 ? 'bg-danger text-white hover:bg-danger/90' : undefined} onClick={() => mutation.mutate()}>{conflicts > 0 ? 'Sostituisci' : 'Importa'}</Button>
        </div>
      </div>
    </Modal>
  </>
}
