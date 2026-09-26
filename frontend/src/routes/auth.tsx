import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLogin } from '@/api/hooks'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/** Accesso di ripiego: di solito RT apre il browser già autenticato (link monouso). */
export function LoginPage() {
  const [params] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const login = useLogin()
  const [token, setToken] = useState('')
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  function submit(event: FormEvent) {
    event.preventDefault()
    login.mutate(token.trim(), { onSuccess: () => navigate(from, { replace: true }) })
  }

  return (
    <main className="flex min-h-dvh items-center justify-center p-4">
      <Card className="w-full max-w-md p-6">
        <h1 className="text-3xl font-bold tracking-tighter">
          rt<span className="text-success">.</span>
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Apri RT dal Mac: il browser si apre già autenticato. In alternativa incolla il token API che RT ha mostrato al
          primo avvio.
        </p>
        {params.get('error') === 'link' && (
          <Alert tone="warning" className="mt-4">
            Il link di accesso è scaduto o è già stato usato. Apri di nuovo RT dal Mac o usa il token.
          </Alert>
        )}
        <form onSubmit={submit} className="mt-5 flex flex-col gap-2">
          <Label htmlFor="token">Token API</Label>
          <Input
            id="token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
          />
          {login.isError && <Alert tone="danger">{errorMessage(login.error)}</Alert>}
          <Button type="submit" className="mt-2" disabled={!token.trim() || login.isPending}>
            Accedi
          </Button>
          <p className="mt-1 text-xs text-muted-foreground">
            Token perso? Se ne può generare uno nuovo sul Mac in cui gira RT: quello vecchio smette di funzionare.
          </p>
        </form>
      </Card>
    </main>
  )
}
