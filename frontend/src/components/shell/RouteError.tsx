import { useEffect } from 'react'
import { isRouteErrorResponse, useRouteError } from 'react-router'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { reportClientLog } from '@/lib/clientLog'

/**
 * Pagina d'errore delle rotte: senza, un errore in un componente mostrava la pagina inglese
 * di React Router con lo stack. L'errore finisce anche in api.log (lib/clientLog).
 */
export function RouteError() {
  const error = useRouteError()
  const notFound = isRouteErrorResponse(error) && error.status === 404
  const detail = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : String(error)

  useEffect(() => {
    if (notFound) return
    reportClientLog('error', `Pagina andata in errore: ${detail}`, error instanceof Error ? (error.stack ?? '') : '')
  }, [detail, error, notFound])

  return (
    <main className="mx-auto flex max-w-xl flex-col gap-3 p-8 text-sm">
      <h1 className="text-base font-semibold">{notFound ? 'Pagina non trovata' : 'Questa pagina ha avuto un problema'}</h1>
      {!notFound && (
        <>
          <p>I tuoi dati non sono stati toccati. Ricarica la pagina; se l&apos;errore si ripete, il dettaglio è già nel registro di RT (api.log).</p>
          <Alert tone="danger" className="break-words font-mono text-xs">{detail}</Alert>
        </>
      )}
      <div className="flex gap-2">
        {!notFound && <Button onClick={() => window.location.reload()}>Ricarica la pagina</Button>}
        <Button variant="outline" onClick={() => window.location.assign('/')}>Torna alle lezioni</Button>
      </div>
    </main>
  )
}
