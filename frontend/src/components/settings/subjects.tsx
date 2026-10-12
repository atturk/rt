import { useState, type FormEvent } from 'react'
import { Plus, X } from 'lucide-react'
import { errorMessage } from '@/api/client'
import { useCreateSubject, useDeleteSubject, useSubjects } from '@/api/subjects'
import { Alert } from '@/components/ui/alert'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Section } from './common'

export function SubjectsSettingsSection() {
  const [newSubject, setNewSubject] = useState('')
  const [error, setError] = useState<string | null>(null)
  const subjectsQuery = useSubjects()
  const createSubject = useCreateSubject()
  const deleteSubject = useDeleteSubject()

  const subjects = [...(subjectsQuery.data ?? [])].sort((a, b) =>
    a.nome.localeCompare(b.nome, undefined, { sensitivity: 'base' }),
  )

  const handleAdd = async (e?: FormEvent) => {
    if (e) e.preventDefault()
    const trimmed = newSubject.trim()
    if (!trimmed) return
    setError(null)
    try {
      await createSubject.mutateAsync(trimmed)
      setNewSubject('')
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const handleDelete = async (nome: string) => {
    setError(null)
    try {
      await deleteSubject.mutateAsync(nome)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <Section id="subjects" title="Materie">
      <p className="text-body text-muted-foreground">
        Compaiono nei menu dell'import, del calendario e dei tipi di domanda. Una materia scritta nell'import o nel calendario si aggiunge da sola.
      </p>

      <form onSubmit={handleAdd} className="flex max-w-md items-center gap-2">
        <Input
          id="newsub"
          placeholder="Nuova materia"
          aria-label="Nuova materia"
          value={newSubject}
          onChange={(e) => setNewSubject(e.target.value)}
        />
        <IconButton
          id="addsub"
          icon={Plus}
          label="Aggiungi"
          disabled={!newSubject.trim() || createSubject.isPending}
          onClick={() => void handleAdd()}
        />
      </form>

      {error && <Alert tone="danger">{error}</Alert>}

      {subjectsQuery.isPending && (
        <p className="text-body text-muted-foreground">Carico le materie…</p>
      )}

      {subjectsQuery.isError && (
        <Alert tone="danger">{errorMessage(subjectsQuery.error)}</Alert>
      )}

      <div id="subs" className="flex max-w-md flex-col divide-y rounded-lg border">
        {subjects.map((sub) => {
          const count = sub.lezioni
          const countText = count === 0 ? 'nessuna lezione' : count === 1 ? '1 lezione' : `${count} lezioni`
          return (
            <div
              key={sub.nome}
              className="group flex items-center justify-between gap-3 px-3 py-2 text-body"
            >
              <span className="min-w-0 flex-1 truncate font-medium">{sub.nome}</span>
              <span className="text-meta text-muted-foreground tabular-nums">{countText}</span>
              {count === 0 ? (
                <IconButton
                  icon={X}
                  label={`Togli ${sub.nome}`}
                  className="opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
                  disabled={deleteSubject.isPending}
                  onClick={() => void handleDelete(sub.nome)}
                />
              ) : (
                <span className="w-[34px]" aria-hidden />
              )}
            </div>
          )
        })}
        {subjects.length === 0 && !subjectsQuery.isPending && (
          <p className="p-3 text-meta text-muted-foreground">Nessuna materia registrata.</p>
        )}
      </div>
    </Section>
  )
}
