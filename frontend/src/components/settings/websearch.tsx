import { useState } from 'react'

import { errorMessage } from '@/api/client'
import { useSaveWebSearch, useTestWebSearch, type Settings } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SettingsGroup, SettingsRow, SettingsSwitch } from './ui'
import { useAutoSave } from './useAutoSave'

/** Ricerca web (RT4-FA5): URL base di SearXNG per la ricerca immagini. */
export function WebSearchSection({ settings }: { settings: Settings }) {
  const save = useSaveWebSearch()
  const contextualVerification = Boolean((settings.web_search as { contextual_verification?: boolean }).contextual_verification)
  const savedUrl = settings.web_search.searxng_base_url ?? ''

  const [urlDraft, setUrlDraft] = useState<{ base: string; value: string } | null>(null)
  const url = urlDraft && urlDraft.base === savedUrl ? urlDraft.value : savedUrl

  const urlAuto = useAutoSave(save, url, {
    delay: 600,
    initial: savedUrl,
    equals: (a, b) => a.trim() === b.trim(),
    serialize: (val) => val.trim(),
  })

  const [switchStatus, setSwitchStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [switchError, setSwitchError] = useState<string | null>(null)

  function toggleContextual(next: boolean) {
    setSwitchStatus('saving')
    setSwitchError(null)
    save.mutate(
      { contextual_verification: next },
      {
        onSuccess: () => {
          setSwitchStatus('saved')
          setTimeout(() => setSwitchStatus((s) => (s === 'saved' ? 'idle' : s)), 1500)
        },
        onError: (err) => {
          setSwitchStatus('error')
          setSwitchError(errorMessage(err))
        },
      },
    )
  }

  return (
    <SettingsGroup
      id="ricerca-web"
      title="Ricerca web"
      description="RT cerca immagini sul web con un'istanza SearXNG che gestisci tu."
    >
      <WebSearchUrlRow
        url={url}
        saved={savedUrl}
        status={urlAuto}
        onChange={(next) => setUrlDraft({ base: savedUrl, value: next })}
        onBlur={urlAuto.flush}
      />
      <SettingsSwitch
        id="wsw"
        testId="toggle-contextual-web-search"
        label="Cerca sul web durante la verifica contestuale"
        info="Le fonti con i link compaiono nella voce di verifica. Spenta, la verifica funziona come oggi."
        checked={contextualVerification}
        disabled={save.isPending}
        onChange={toggleContextual}
        status={{ status: switchStatus, error: switchError, retry: () => toggleContextual(contextualVerification) }}
      />
    </SettingsGroup>
  )
}

function WebSearchUrlRow({
  url,
  saved,
  status,
  onChange,
  onBlur,
}: {
  url: string
  saved: string
  status: ReturnType<typeof useAutoSave<string, string>>
  onChange: (next: string) => void
  onBlur: () => void
}) {
  const test = useTestWebSearch()
  const current = test.variables === url.trim()

  let outcome = null
  if (current && test.isPending) {
    outcome = (
      <p role="status" className="text-meta text-muted-foreground">
        Ricerca di prova in corso…
      </p>
    )
  } else if (current && test.isError) {
    outcome = <Alert tone="danger">{errorMessage(test.error)}</Alert>
  } else if (current && test.data) {
    outcome = test.data.ok ? (
      <p role="status" className="text-meta text-success" data-testid="searxng-test-result">
        {test.data.message}
        {test.data.latency_ms != null && ` (${test.data.latency_ms} ms)`}
      </p>
    ) : (
      <Alert tone="danger" data-testid="searxng-test-result">
        {test.data.message}
      </Alert>
    )
  }

  return (
    <SettingsRow
      label="URL base di SearXNG"
      htmlFor="searxng-url"
      info="Nelle impostazioni di SearXNG deve essere abilitato il formato json (search.formats), altrimenti la ricerca non restituisce risultati."
      description={saved ? undefined : 'Non impostato: la ricerca immagini web non è disponibile.'}
      status={status}
      control={
        <div className="flex w-full flex-col gap-2 @sm:w-auto @sm:items-end">
          <div className="flex w-full items-center gap-2 @sm:w-80">
            <Input
              id="searxng-url"
              inputMode="url"
              value={url}
              placeholder="http://localhost:8088"
              onChange={(e) => onChange(e.target.value)}
              onBlur={onBlur}
            />
            <Button
              type="button"
              variant="outline"
              disabled={!url.trim() || (current && test.isPending)}
              onClick={() => test.mutate(url.trim())}
            >
              Prova
            </Button>
          </div>
          {outcome}
        </div>
      }
    />
  )
}
