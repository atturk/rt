import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, errorMessage, unwrap } from '@/api/client'
import { useSettings, useSystemInfo } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { ConfirmDialog } from '@/components/ui/dialog'
import { formatBytes } from '@/lib/jobs'
import { SettingsDisclosure, SettingsGroup } from './ui'
import { UpdateSection } from './update'

/** Scheda Info: versione e canale di aggiornamento (come 'rt -v'; il canale si cambia con
 * 'rt -u --beta' / '--stable'), cartelle e runtime. Utile da copiare in una segnalazione. */
export function InfoSection() {
  const info = useSystemInfo()
  // Database e media del processo: di solito la cartella dati, ma con una lessons_root 3.x è un'altra.
  const inUse = useSettings().data?.data_dir
  return (
    <>
      <SettingsGroup
        id="info"
        title="Info"
        description="Versione di RT, canale di aggiornamento e cartelle in uso: utili da allegare a una segnalazione."
      >
        {info.isPending && <p className="px-4 py-3 text-body text-muted-foreground">Carico le informazioni…</p>}
        {info.isError && (
          <div className="px-4 py-3">
            <Alert tone="danger">{errorMessage(info.error)}</Alert>
          </div>
        )}
        {info.data && (
          <dl className="divide-y divide-border/60 text-body" data-testid="system-info">
            <InfoRow label="Versione">
              <span className="inline-flex items-center gap-2">
                <span className="font-semibold tabular-nums">{info.data.version}</span>
                {info.data.prerelease && <Badge tone="warning">Beta</Badge>}
              </span>
            </InfoRow>
            {info.data.build && (
              <InfoRow label="Build">
                <span className="tabular-nums">{info.data.build}</span>
              </InfoRow>
            )}
            <InfoRow label="Canale di aggiornamento">
              {info.data.update_channel === 'beta' ? 'Beta (anche le versioni di prova)' : 'Stabile'}
            </InfoRow>
            <InfoRow label="Cartella dati"><Path value={info.data.data_dir} /></InfoRow>
            {inUse && inUse !== info.data.data_dir && <InfoRow label="Database e media in uso"><Path value={inUse} /></InfoRow>}
            <InfoRow label="Configurazione"><Path value={info.data.config_dir} /></InfoRow>
            <InfoRow label="Installazione"><Path value={info.data.install_dir} /></InfoRow>
            <InfoRow label="Python">{info.data.python_version}</InfoRow>
            <InfoRow label="Sistema">{info.data.platform}</InfoRow>
          </dl>
        )}
      </SettingsGroup>
      <UpdateSection />
      <ChangelogSection version={info.data?.version} />
      <CacheSection />
    </>
  )
}

/** Note distribuite con RT: nessun HTML o renderer Markdown. */
export function ChangelogSection({ version }: { version?: string }) {
  const changelog = useQuery({ queryKey: ['system', 'changelog'], queryFn: () => unwrap(api.GET('/api/v1/system/changelog')) })
  const sections = Array.isArray(changelog.data) ? changelog.data : []
  return (
    <SettingsGroup id="novita" title="Novità">
      {changelog.isPending && <p className="px-4 py-3 text-body text-muted-foreground">Carico le novità…</p>}
      {changelog.isError && (
        <div className="px-4 py-3">
          <Alert tone="danger">{errorMessage(changelog.error)}</Alert>
        </div>
      )}
      {changelog.isSuccess && sections.length === 0 && (
        <p className="px-4 py-3 text-body text-muted-foreground">Nessuna nota disponibile.</p>
      )}
      {sections.map(section => (
        <SettingsDisclosure
          key={`${section.version}:${version}`}
          defaultOpen={section.version === version}
          label={section.version}
          summary={section.date || undefined}
        >
          {section.groups.map((group, index) => (
            <div key={index} className={index > 0 ? 'mt-3' : undefined}>
              <h4 className="text-meta font-medium text-muted-foreground">{group.title}</h4>
              <ul className="mt-1 space-y-1 text-body">
                {group.items.map(item => (
                  <ChangelogItem key={JSON.stringify([section.version, item])} version={section.version} text={item} />
                ))}
              </ul>
            </div>
          ))}
        </SettingsDisclosure>
      ))}
    </SettingsGroup>
  )
}

function ChangelogItem({ version, text }: { version: string; text: string }) {
  const storageKey = `rt.changelog.checked:${JSON.stringify([version, text])}`
  const [checked, setChecked] = useState(() => {
    try { return localStorage.getItem(storageKey) === '1' } catch { return false }
  })
  return (
    <li>
      <label className="flex cursor-pointer items-start gap-2">
        <Checkbox
          label={text.replace(/\*\*/g, '')}
          checked={checked}
          className="mt-1"
          onChange={value => {
            setChecked(value)
            try {
              if (value) localStorage.setItem(storageKey, '1')
              else localStorage.removeItem(storageKey)
            } catch { /* La casella resta utilizzabile senza memoria del browser. */ }
          }}
        />
        <span className={checked ? 'text-muted-foreground line-through' : undefined}>
          {text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <strong key={i}>{part}</strong> : part))}
        </span>
      </label>
    </li>
  )
}

const cacheKey = ['system', 'cache'] as const
const compactAudioPreviewKey = ['system', 'compact-audio', 'preview'] as const
const cacheSize = (bytes: number) => bytes === 0 ? '0 B' : formatBytes(bytes)

export function CacheSection() {
  const client = useQueryClient()
  const [confirm, setConfirm] = useState(false)
  const [confirmCompact, setConfirmCompact] = useState(false)
  const cache = useQuery({ queryKey: cacheKey, queryFn: () => unwrap(api.GET('/api/v1/system/cache')) })
  const compactPreview = useQuery({
    queryKey: compactAudioPreviewKey,
    queryFn: () => unwrap(api.GET('/api/v1/system/compact-audio/preview')),
  })
  const clear = useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/system/cache')),
    onSuccess: async () => {
      setConfirm(false)
      await client.invalidateQueries({ queryKey: cacheKey })
    },
  })
  const compact = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/system/compact-audio')),
    onSuccess: async () => {
      setConfirmCompact(false)
      await client.invalidateQueries({ queryKey: compactAudioPreviewKey })
    },
  })
  const liberabili = compactPreview.data?.spazio_stimato_liberato ?? 0

  return (
    <SettingsGroup id="cache" title="Spazio e cache" description="La cache si rigenera da sola quando serve.">
      {cache.isPending && <p className="px-4 py-3 text-body text-muted-foreground">Calcolo lo spazio…</p>}
      {cache.isError && (
        <div className="px-4 py-3">
          <Alert tone="danger">{errorMessage(cache.error)}</Alert>
        </div>
      )}
      {cache.data && (
        <dl className="divide-y divide-border/60 text-body">
          <InfoRow label="Audio">{cacheSize(cache.data.audio.bytes)} · {cache.data.audio.entries} file</InfoRow>
          <InfoRow label="Forme d’onda">{cacheSize(cache.data.waveform.bytes)} · {cache.data.waveform.entries} file</InfoRow>
          <InfoRow label="Totale"><span className="font-semibold tabular-nums">{cacheSize(cache.data.total.bytes)}</span></InfoRow>
          {compactPreview.data && (
            <InfoRow label="Audio convertibile">
              {liberabili > 0 ? (
                <span>
                  ~{cacheSize(liberabili)} liberabili
                  <span className="ml-2 text-meta text-muted-foreground">
                    ({compactPreview.data.file_convertibili} file da convertire
                    {compactPreview.data.file_orfani > 0 ? `, ${compactPreview.data.file_orfani} orfani` : ''})
                  </span>
                </span>
              ) : (
                <span className="text-muted-foreground">Tutti gli audio sono già compressi</span>
              )}
            </InfoRow>
          )}
        </dl>
      )}
      <div className="flex flex-col gap-2 px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" disabled={!cache.data?.total.entries || clear.isPending}
            onClick={() => { clear.reset(); setConfirm(true) }}>Svuota la cache</Button>
          <Button variant="outline" disabled={liberabili <= 0 || compact.isPending}
            onClick={() => { compact.reset(); setConfirmCompact(true) }}>Alleggerisci l’audio delle lezioni</Button>
        </div>
        {clear.isSuccess && <p role="status" className="text-meta text-success">Liberati {cacheSize(clear.data.total.bytes)}.</p>}
        {compact.isSuccess && <p role="status" className="text-meta text-success">Operazione avviata: controlla l’avanzamento nei Job.</p>}
      </div>
      <ConfirmDialog open={confirm} title="Svuota la cache" confirmLabel="Svuota"
        confirmDisabled={clear.isPending} onCancel={() => setConfirm(false)} onConfirm={() => clear.mutate()}>
        <p>Svuotare la cache{cache.data ? ` (${cacheSize(cache.data.total.bytes)})` : ''}?</p>
        {clear.isError && <Alert tone="danger" className="mt-3">{errorMessage(clear.error)}</Alert>}
      </ConfirmDialog>
      <ConfirmDialog open={confirmCompact} title="Alleggerisci l’audio delle lezioni" confirmLabel="Alleggerisci"
        confirmDisabled={compact.isPending} onCancel={() => setConfirmCompact(false)} onConfirm={() => compact.mutate()}>
        <p>
          Convertire in AAC (.m4a) i file WAV e FLAC delle fonti e rimuovere gli audio uniti non più utilizzati?
          {liberabili > 0 && <> Si stima di liberare circa <strong>{cacheSize(liberabili)}</strong>.</>}
        </p>
        {compact.isError && <Alert tone="danger" className="mt-3">{errorMessage(compact.error)}</Alert>}
      </ConfirmDialog>
    </SettingsGroup>
  )
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-x-6 gap-y-1 px-4 py-2.5 sm:grid-cols-[12rem_1fr]">
      <dt className="text-meta font-medium text-muted-foreground sm:pt-0.5">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  )
}

function Path({ value }: { value: string }) {
  return <code className="break-all text-meta">{value}</code>
}
