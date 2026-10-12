import { useState, type FormEvent } from 'react'

import { errorMessage } from '@/api/client'
import { useSaveWebSearch, useTestWebSearch, type Settings } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field, SaveFeedback, Section } from './common'

/** Ricerca web (RT4-FA5): URL base di SearXNG per la ricerca immagini. Il salvataggio va nelle
 * impostazioni e l'aggiunta immagini lo rilegge a ogni job. */
export function WebSearchSection({ settings }: { settings: Settings }) {
  const save = useSaveWebSearch()
  const contextualVerification = Boolean((settings.web_search as any).contextual_verification)

  return (
    <Section
      id="ricerca-web"
      title="Ricerca web"
      description={
        <>
          RT cerca immagini sul web con un'istanza SearXNG che gestisci tu. Nelle impostazioni di SearXNG deve essere abilitato il formato
          json (search.formats), altrimenti la ricerca non restituisce risultati.
        </>
      }
    >
      <WebSearchForm key={settings.web_search.searxng_base_url ?? ''} saved={settings.web_search.searxng_base_url ?? ''} save={save} />
      <div className="mt-6 border-t border-border/60 pt-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-col gap-0.5">
            <span className="text-body font-medium text-foreground">
              Cerca sul web durante la verifica contestuale
            </span>
            <span className="text-meta text-muted-foreground">
              Le fonti con i link compaiono nella voce di verifica. Spenta, la verifica funziona come oggi.
            </span>
          </div>
          <Button
            id="wsw"
            role="switch"
            aria-label="Ricerca web nella verifica"
            aria-checked={contextualVerification}
            variant={contextualVerification ? 'default' : 'outline'}
            size="sm"
            disabled={save.isPending}
            onClick={() => save.mutate({ contextual_verification: !contextualVerification })}
            data-testid="toggle-contextual-web-search"
          >
            {contextualVerification ? 'Sì' : 'No'}
          </Button>
        </div>
      </div>
      <SaveFeedback mutation={save} />
    </Section>
  )
}

function WebSearchForm({ saved, save }: { saved: string; save: ReturnType<typeof useSaveWebSearch> }) {
  const [url, setUrl] = useState(saved)
  const test = useTestWebSearch()
  const current = test.variables === url.trim()

  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate(url.trim())
  }

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
    <form className="flex flex-col gap-3" onSubmit={submit} aria-label="SearXNG">
      <Field
        label="URL base di SearXNG"
        htmlFor="searxng-url"
        hint={saved ? `Salvato: ${saved}` : 'Non impostato: la ricerca immagini web non è disponibile.'}
      >
        <Input id="searxng-url" inputMode="url" value={url} placeholder="http://localhost:8088" onChange={(e) => setUrl(e.target.value)} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={save.isPending || url.trim() === saved}>
          Salva
        </Button>
        <Button variant="outline" disabled={!url.trim() || (current && test.isPending)} onClick={() => test.mutate(url.trim())}>
          Prova
        </Button>
      </div>
      {outcome}
    </form>
  )
}
