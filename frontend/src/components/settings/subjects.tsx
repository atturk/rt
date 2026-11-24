import { useState, type FormEvent } from 'react'
import { Plus, X } from 'lucide-react'

import { errorMessage } from '@/api/client'
import { useCreateSubject, useDeleteSubject, useSubjects, useSubjectTeachers, type SubjectItem } from '@/api/subjects'
import { Alert } from '@/components/ui/alert'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { usePreference } from '@/lib/preferences'
import { CalendarScheduleSettings } from './CalendarScheduleSettings'
import { SettingsGroup, SettingsPage, SettingsRow, SettingsSwitch } from './ui'

function TeacherRow({ subject, onError }: { subject: SubjectItem; onError: (error: string | null) => void }) {
  const [name, setName] = useState('')
  const mutation = useSubjectTeachers()
  const save = async (nome: string, remove = false) => {
    if (!nome.trim()) return
    onError(null)
    try {
      await mutation.mutateAsync({ materia: subject.nome, nome: nome.trim(), remove })
      if (!remove) setName('')
    } catch (error) {
      onError(errorMessage(error))
    }
  }
  return (
    <form className="flex flex-wrap items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); void save(name) }}>
      {(subject.docenti ?? []).map((teacher) => (
        <span key={teacher} className="inline-flex items-center gap-1 rounded-full border px-2 text-meta">
          {teacher}
          <IconButton
            icon={X}
            label={`Togli ${teacher} da ${subject.nome}`}
            className="size-6 min-h-6 min-w-6"
            disabled={mutation.isPending}
            onClick={() => void save(teacher, true)}
          />
        </span>
      ))}
      <Input
        className="h-7 w-40 text-meta"
        aria-label={`Aggiungi docente a ${subject.nome}`}
        placeholder="Aggiungi docente"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <IconButton
        type="submit"
        icon={Plus}
        label={`Aggiungi docente a ${subject.nome}`}
        disabled={!name.trim() || mutation.isPending}
      />
    </form>
  )
}

export function SubjectsSettingsSection() {
  const [newSubject, setNewSubject] = useState('')
  const [error, setError] = useState<string | null>(null)
  const subjectsQuery = useSubjects()
  const createSubject = useCreateSubject()
  const deleteSubject = useDeleteSubject()

  const dataList = Array.isArray(subjectsQuery.data) ? subjectsQuery.data : []
  const subjects = [...dataList].sort((a, b) =>
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
    <SettingsGroup
      id="subjects"
      title="Materie"
      description="Ogni materia ha i suoi docenti, proposti quando compili il campo Docente."
      footer="Un docente scritto in una lezione o nel calendario si aggiunge da solo."
    >
      <SettingsRow
        label="Aggiungi materia"
        htmlFor="newsub"
        control={
          <form onSubmit={handleAdd} className="flex w-full items-center gap-2 @sm:w-60">
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
        }
      />
      {error && (
        <div className="px-4 py-3">
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      {subjectsQuery.isPending && (
        <p className="px-4 py-3 text-body text-muted-foreground">Carico le materie…</p>
      )}
      {subjectsQuery.isError && (
        <div className="px-4 py-3">
          <Alert tone="danger">{errorMessage(subjectsQuery.error)}</Alert>
        </div>
      )}
      <div id="subs" className="divide-y divide-border/60">
        {subjects.map((sub) => {
          const count = sub.lezioni
          const countText = count === 0 ? 'nessuna lezione' : count === 1 ? '1 lezione' : `${count} lezioni`
          return (
            <div key={sub.nome} className="group flex flex-col gap-2 px-4 py-3 text-body">
              <div className="flex items-center justify-between gap-3">
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
              <TeacherRow subject={sub} onError={setError} />
            </div>
          )
        })}
        {subjects.length === 0 && !subjectsQuery.isPending && (
          <p className="px-4 py-3 text-meta text-muted-foreground">Nessuna materia registrata.</p>
        )}
      </div>
    </SettingsGroup>
  )
}

export function SubjectsCalendarSection() {
  const [enabled, setEnabled] = usePreference('calendar.missing-warning', true)
  const [calendarError, setCalendarError] = useState<string | null>(null)

  return (
    <SettingsPage
      title="Materie e calendario"
      description="Elenco delle materie con i rispettivi docenti, avvisi e orario delle lezioni."
    >
      <SubjectsSettingsSection />
      <SettingsGroup id="calendario" title="Calendario">
        <SettingsSwitch
          id="calendar-missing-warning"
          label="Avviso lezioni mancanti"
          info="Segnala quando una lezione prevista dall’orario non è ancora stata caricata."
          checked={enabled}
          onChange={setEnabled}
        />
        <CalendarScheduleSettings onError={setCalendarError} />
        {calendarError && (
          <div className="px-4 py-3">
            <Alert tone="danger">{calendarError}</Alert>
          </div>
        )}
      </SettingsGroup>
    </SettingsPage>
  )
}
