import { ChevronRight, CornerLeftUp, Folder, FolderOpen, Home } from 'lucide-react'
import { useState } from 'react'

import { errorMessage } from '@/api/client'
import { useChooseFolder, useFolders } from '@/api/settings'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/**
 * Scelta di una cartella senza digitare il percorso (RT4-FA6). "Scegli cartella…" apre la
 * finestra di Finder tramite l'API; se non è disponibile (o viene annullata) si apre il
 * navigatore delle cartelle della home. Il percorso a mano resta l'alternativa.
 * Il valore è quello del form: si salva con il pulsante del form che lo contiene.
 */
export function FolderField({ id, value, onChange }: { id: string; value: string; onChange: (path: string) => void }) {
  const choose = useChooseFolder()
  const [manual, setManual] = useState(false)
  const [browsing, setBrowsing] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  function openChooser() {
    setNotice(null)
    choose.mutate(value.startsWith('/') ? value : null, {
      onSuccess: (result) => {
        if (result.status === 'chosen' && result.path) {
          onChange(result.path)
          setBrowsing(false)
          return
        }
        setNotice(result.status === 'cancelled' ? 'Nessuna cartella scelta: puoi sceglierla qui sotto.' : null)
        setBrowsing(true)
      },
      onError: () => setBrowsing(true),
    })
  }

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>Cartella delle lezioni</Label>
      {/* Sola lettura finché non si sceglie di scrivere il percorso a mano. */}
      <Input
        id={id}
        value={value}
        readOnly={!manual}
        onChange={(e) => onChange(e.target.value)}
        placeholder={manual ? '~/RT Lezioni' : 'Nessuna cartella scelta'}
        className={manual ? undefined : 'bg-muted/40 font-mono text-xs'}
        required
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={openChooser} disabled={choose.isPending}>
          <FolderOpen /> Scegli cartella…
        </Button>
        {!manual && (
          <Button
            variant="link"
            size="sm"
            onClick={() => {
              setManual(true)
              document.getElementById(id)?.focus()
            }}
          >
            Inserisci il percorso a mano
          </Button>
        )}
      </div>
      {choose.isPending && (
        <p role="status" className="text-xs text-muted-foreground">
          Scegli la cartella nella finestra di Finder…
        </p>
      )}
      {notice && <p className="text-xs text-muted-foreground">{notice}</p>}
      {browsing && (
        <FolderBrowser
          start={value}
          onPick={(path) => {
            onChange(path)
            setBrowsing(false)
            setNotice(null)
          }}
          onClose={() => setBrowsing(false)}
        />
      )}
      <p className="text-[11px] text-muted-foreground">Se la cartella non esiste RT la crea.</p>
    </div>
  )
}

/** Navigatore: sottocartelle della home (niente file), una cartella alla volta. */
function FolderBrowser({ start, onPick, onClose }: { start: string; onPick: (path: string) => void; onClose: () => void }) {
  const [path, setPath] = useState<string | null>(null)
  const folders = useFolders(path, true)
  const data = folders.data
  // Se la cartella iniziale è nella home si parte da lì (una volta sola).
  const [tried, setTried] = useState(false)
  if (!tried && data && path === null && start.startsWith(data.home + '/')) {
    setTried(true)
    setPath(start)
  }
  return (
    <div role="group" aria-label="Navigatore delle cartelle" className="flex flex-col gap-2 rounded-lg border p-3" data-testid="folder-browser">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Button variant="ghost" size="sm" aria-label="Home" onClick={() => setPath(null)} disabled={path === null}>
          <Home />
        </Button>
        <Button variant="ghost" size="sm" aria-label="Cartella superiore" onClick={() => data?.parent && setPath(data.parent)} disabled={!data?.parent}>
          <CornerLeftUp />
        </Button>
        <code className="break-all" data-testid="browser-path">
          {data?.path ?? '…'}
        </code>
      </div>
      {folders.isError && <Alert tone="danger">{errorMessage(folders.error)}</Alert>}
      {data && (
        <ul className="flex max-h-60 flex-col overflow-y-auto rounded-md border" aria-label="Sottocartelle">
          {data.folders.length === 0 && <li className="px-3 py-2 text-xs text-muted-foreground">Nessuna sottocartella.</li>}
          {data.folders.map((f) => (
            <li key={f.path}>
              <button
                type="button"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted"
                onClick={() => setPath(f.path)}
              >
                <Folder className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="truncate">{f.name}</span>
                <ChevronRight className="ml-auto size-4 text-muted-foreground" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => data && onPick(data.path)} disabled={!data}>
          Usa questa cartella
        </Button>
        <Button variant="outline" size="sm" onClick={onClose}>
          Chiudi
        </Button>
      </div>
    </div>
  )
}
