import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Download, Pencil, Plus, RotateCw, Trash2, Upload } from 'lucide-react'
import { errorMessage } from '@/api/client'
import { useRecallRules, useSaveRecallVotes, useEditRecallRules, useUpdateRecallRules } from '@/api/recallRules'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import { useLessons } from '@/api/hooks'
import { useSubjects } from '@/api/subjects'
import { useStudyLesson } from '@/api/recall'
import { exportQuestionType, useQuestionSettings, useSaveQuestionType, useDeleteQuestionType, useImportQuestionType, useQuestionTrial, type QuestionDefinition, type QuestionSettings } from '@/api/questionSettings'
import { TypeIcon } from '@/components/recall/TypeIcon'
import { TYPE_ICON_NAMES } from '@/lib/typeIcons'
import { QUESTION_TYPE_LABELS } from '@/lib/questionTypes'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { AutoSaveStatus, SettingsDisclosure, SettingsGroup, SettingsPage, SettingsRow, SettingsSelect, SettingsSwitch } from './ui'
import { useAutoSave } from './useAutoSave'

const empty: QuestionDefinition = { id: '', nome: '', icona: 'MessageSquare', materie: [], cerca: '', anche_adatti: false, continua: false, chiedi: '', correzione: 'testo', varianti: false }

export function QuestionsSettingsSection() {
  const query = useQuestionSettings()
  if (query.isError) return <Alert tone="danger">{errorMessage(query.error)}</Alert>
  return (
    <SettingsPage
      title="Domande"
      description="Regole imparate dai tuoi voti, tipi personalizzati per materia e modelli pronti."
    >
      {query.data ? <QuestionsSettings data={query.data} /> : <p className="text-body text-muted-foreground">Carico i tipi di domanda…</p>}
    </SettingsPage>
  )
}

function QuestionsSettings({ data }: { data: QuestionSettings }) {
  const file = useRef<HTMLInputElement>(null)
  const save = useSaveQuestionType()
  const remove = useDeleteQuestionType()
  const importing = useImportQuestionType()
  const subjectsQuery = useSubjects()
  const [editor, setEditor] = useState<{ definition: QuestionDefinition; id?: string } | null>(null)
  const [deleting, setDeleting] = useState<QuestionDefinition | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  async function importFile(selected?: File) {
    if (!selected) return
    setError(null)
    try {
      const text = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsText(selected) })
      let definition: QuestionDefinition
      try { definition = JSON.parse(text) } catch { throw new Error('File JSON non valido.') }
      const added = await importing.mutateAsync(definition)
      setNotice(`Importato: ${added.nome} (${added.id}).`)
      setEditor(null)
    } catch (failure) { setError(errorMessage(failure)) }
    if (file.current) file.current.value = ''
  }
  function submit(definition: QuestionDefinition) {
    save.mutate({ definition, id: editor?.id }, { onSuccess: () => { setEditor(null); setNotice('Tipo salvato.') } })
  }
  return (
    <>
      <VoteRulesSettings />
      <SettingsGroup id="question-types" title="Tipi personalizzati" description="Definisci domande su misura per le tue materie.">
        <div className="flex flex-wrap gap-2 px-4 py-3">
          <Button size="sm" onClick={() => { setEditor({ definition: { ...empty } }); setNotice(null); save.reset() }}>
            <Plus aria-hidden />Nuovo tipo
          </Button>
          <Button size="sm" variant="outline" disabled={importing.isPending} onClick={() => file.current?.click()}>
            <Upload aria-hidden />Importa
          </Button>
          <input ref={file} type="file" accept=".json,application/json" aria-label="Importa tipo JSON" className="sr-only" onChange={event => void importFile(event.target.files?.[0])} />
        </div>
        {data.types.length === 0 && (
          <p className="px-4 py-3 text-body text-muted-foreground">Nessun tipo personalizzato.</p>
        )}
        {data.types.map(type => (
          <div key={type.id} className="flex min-h-12 flex-wrap items-center gap-3 px-4 py-3" data-testid={`question-type-${type.id}`}>
            <TypeIcon name={type.icona} />
            <div className="min-w-0 flex-1">
              <p className="text-body font-medium text-foreground">{type.nome}</p>
              {type.materie.length > 0 && <p className="text-meta text-muted-foreground">{type.materie.join(', ')}</p>}
            </div>
            <div className="flex items-center gap-0.5">
              <IconButton label={`Modifica ${type.nome}`} icon={Pencil} onClick={() => { setEditor({ definition: { ...empty, ...type }, id: type.id }); save.reset() }} />
              <IconButton label={`Esporta ${type.nome}`} icon={Download} onClick={() => { void exportQuestionType(type.id ?? '').catch(failure => setError(errorMessage(failure))) }} />
              <IconButton label={`Elimina ${type.nome}`} icon={Trash2} onClick={() => setDeleting(type)} />
            </div>
          </div>
        ))}
        {notice && <p role="status" className="px-4 py-2 text-meta text-success">{notice}</p>}
        {(error || importing.isError || remove.isError) && (
          <div className="px-4 py-3">
            <Alert tone="danger">{error ?? errorMessage(importing.error ?? remove.error)}</Alert>
          </div>
        )}
      </SettingsGroup>
      {editor && (
        <QuestionTypeEditor
          key={`${editor.id ?? 'new'}:${editor.definition.nome}`}
          initial={editor.definition}
          existing={Boolean(editor.id)}
          subjects={Array.isArray(subjectsQuery.data) ? subjectsQuery.data.map((s) => s.nome) : data.materie}
          onSave={submit}
          onCancel={() => setEditor(null)}
          pending={save.isPending}
          error={save.error ? errorMessage(save.error) : null}
        />
      )}
      <SettingsGroup id="question-gallery" title="Galleria dei modelli pronti" description="Scegli un modello pronto da copiare e adattare alle tue materie.">
        <ul className="grid gap-3 p-4 sm:grid-cols-2">
          {data.templates.map(template => (
            <li key={template.id} className="flex items-center gap-3 rounded-lg border bg-background px-3 py-2.5">
              <TypeIcon name={template.icona} />
              <span className="min-w-0 flex-1 truncate text-body">{template.nome}</span>
              <Button
                size="sm"
                variant="outline"
                aria-label={`Usa ${template.nome}`}
                onClick={() => { setEditor({ definition: { ...empty, ...template, id: '', materie: [], correzione: template.correzione as QuestionDefinition['correzione'] } }); save.reset() }}
              >
                Usa
              </Button>
            </li>
          ))}
        </ul>
      </SettingsGroup>
      <ConfirmDialog
        open={Boolean(deleting)}
        title="Elimina tipo"
        confirmLabel="Elimina"
        onCancel={() => setDeleting(null)}
        confirmDisabled={remove.isPending}
        onConfirm={() => { if (deleting?.id) remove.mutate(deleting.id, { onSuccess: () => { setDeleting(null); setEditor(null) } }) }}
      >
        Le domande già generate resteranno nello storico.
      </ConfirmDialog>
    </>
  )
}

function QuestionTypeEditor({ initial, existing, subjects, onSave, onCancel, pending, error }: {
  initial: QuestionDefinition; existing: boolean; subjects: string[]; onSave: (definition: QuestionDefinition) => void; onCancel: () => void; pending: boolean; error: string | null
}) {
  const [draft, setDraft] = useState(initial)
  const [lessonId, setLessonId] = useState(0)
  const [unitId, setUnitId] = useState('')
  const lessons = useLessons()
  const study = useStudyLesson(lessonId || null)
  const trial = useQuestionTrial()
  const set = <K extends keyof QuestionDefinition>(key: K, value: QuestionDefinition[K]) => { setDraft(old => ({ ...old, [key]: value })); trial.reset() }
  const selectedLessons = (lessons.data ?? []).filter(lesson => !lesson.is_sample && draft.materie.some(materia => materia.toLocaleLowerCase() === lesson.materia.toLocaleLowerCase()))
  const valid = draft.nome.trim() && draft.cerca.trim() && draft.chiedi.trim() && draft.materie.length > 0
  const trialDefinition = () => ({ ...draft })
  function submit(event: FormEvent) { event.preventDefault(); onSave(trialDefinition()) }
  return (
    <SettingsGroup id="question-editor" title={existing ? 'Modifica tipo' : 'Nuovo tipo'}>
      <form onSubmit={submit} className="divide-y divide-border/60">
        <SettingsRow
          label="Nome"
          htmlFor="question-name"
          info="Il nome compare nei controlli Genera e nel ripasso."
          control={<Input id="question-name" className="w-full @sm:w-60" required maxLength={100} value={draft.nome} onChange={event => set('nome', event.target.value)} />}
        />
        <SettingsRow
          label="Identificativo"
          htmlFor="question-id"
          info="Nasce dal nome al salvataggio e resta stabile quando il nome cambia."
          control={<Input id="question-id" className="w-full @sm:w-60" readOnly value={draft.id || 'Generato dal nome'} />}
        />
        <SettingsRow
          label="Icona"
          htmlFor="question-icon"
          info="Scegli l’icona che accompagna il nome del tipo."
          control={
            <div className="flex w-full items-center gap-2 @sm:w-60">
              <TypeIcon name={draft.icona} />
              <SettingsSelect id="question-icon" className="min-w-0 flex-1" value={draft.icona} onChange={event => set('icona', event.target.value)}>
                {Array.from(new Set([...TYPE_ICON_NAMES, draft.icona ?? 'MessageSquare'])).map(icon => <option key={icon} value={icon}>{icon}</option>)}
              </SettingsSelect>
            </div>
          }
        />
        <SettingsRow
          label="Materie"
          htmlFor="question-subjects"
          info="Il tipo è disponibile soltanto nelle materie selezionate."
          stacked
          control={
            <fieldset id="question-subjects" className="flex flex-wrap gap-3">
              <legend className="sr-only">Materie</legend>
              {Array.from(new Set([...subjects, ...draft.materie])).map(subject => (
                <label key={subject} className="flex items-center gap-2 text-body">
                  <input
                    type="checkbox"
                    checked={draft.materie.includes(subject)}
                    onChange={event => set('materie', event.target.checked ? [...draft.materie, subject] : draft.materie.filter(m => m !== subject))}
                  />
                  {subject}
                </label>
              ))}
            </fieldset>
          }
        />
        <SettingsRow
          label="Cerca"
          htmlFor="question-find"
          info="Descrivi ciò che il classificatore deve riconoscere nella lezione."
          stacked
          control={<Textarea id="question-find" required maxLength={12000} rows={3} value={draft.cerca} onChange={event => set('cerca', event.target.value)} />}
        />
        <SettingsSwitch
          id="question-adapt"
          label="Anche contenuti adatti"
          info="Include contenuti che si prestano al tipo anche senza un esempio esplicito."
          checked={draft.anche_adatti ?? false}
          onChange={checked => set('anche_adatti', checked)}
        />
        <SettingsSwitch
          id="question-continue"
          label="Unità consecutive"
          info="Due unità consecutive marcate vengono inviate insieme al generatore."
          checked={draft.continua ?? false}
          onChange={checked => set('continua', checked)}
        />
        <SettingsRow
          label="Chiedi"
          htmlFor="question-instructions"
          info="Indica come scrivere una domanda; la risposta dello studente è sempre testuale."
          stacked
          control={<Textarea id="question-instructions" required maxLength={24000} rows={5} value={draft.chiedi} onChange={event => set('chiedi', event.target.value)} />}
        />
        <SettingsRow
          label="Correzione"
          htmlFor="question-correction"
          info="La valutazione usa la soluzione generata oppure il testo delle subunità."
          control={
            <SettingsSelect id="question-correction" className="w-full @sm:w-60" value={draft.correzione} onChange={event => set('correzione', event.target.value as QuestionDefinition['correzione'])}>
              <option value="testo">Testo della lezione</option>
              <option value="soluzione">Soluzione attesa</option>
            </SettingsSelect>
          }
        />
        <SettingsSwitch
          id="question-variants"
          label="Varianti verificate"
          info="Permette nuove varianti, controllate in modo indipendente prima di proporle."
          checked={draft.varianti ?? false}
          onChange={checked => set('varianti', checked)}
        />
        <div className="flex flex-col gap-3 px-4 py-3">
          <div className="flex gap-2">
            <Button type="submit" disabled={pending || !valid}>Salva tipo</Button>
            <Button type="button" variant="outline" disabled={pending} onClick={onCancel}>Annulla</Button>
          </div>
          {error && <Alert tone="danger">{error}</Alert>}
        </div>
      </form>
      <SettingsDisclosure label="Prova su un’unità" summary="Senza salvare">
        <div className="-mx-4 -my-3 divide-y divide-border/60">
          <SettingsRow
            label="Lezione"
            htmlFor="question-trial-lesson"
            control={
              <SettingsSelect id="question-trial-lesson" className="w-full @sm:w-60" value={lessonId} onChange={event => { setLessonId(Number(event.target.value)); setUnitId(''); trial.reset() }}>
                <option value={0}>Scegli una lezione</option>
                {selectedLessons.map(lesson => <option key={lesson.id} value={lesson.id}>{lesson.titolo || lesson.folder_name}</option>)}
              </SettingsSelect>
            }
          />
          <SettingsRow
            label="Unità"
            htmlFor="question-trial-unit"
            control={
              <SettingsSelect id="question-trial-unit" className="w-full @sm:w-60" value={unitId} onChange={event => { setUnitId(event.target.value); trial.reset() }}>
                <option value="">Scegli un’unità</option>
                {(study.data?.units ?? []).map(unit => <option key={unit.id} value={unit.id}>{unit.id} · {unit.title}</option>)}
              </SettingsSelect>
            }
          />
          <div className="flex flex-col gap-3 px-4 py-3">
            {(lessons.isError || study.isError) && <Alert tone="danger">{errorMessage(lessons.error ?? study.error)}</Alert>}
            <div>
              <Button variant="outline" disabled={!valid || !lessonId || !unitId || trial.isPending} onClick={() => trial.mutate({ definition: trialDefinition(), lesson_id: lessonId, unit_id: unitId, mock: false })}>
                {trial.isPending ? 'Provo…' : 'Prova'}
              </Button>
            </div>
            {trial.isError && <Alert tone="danger">{errorMessage(trial.error)}</Alert>}
            {trial.data && (
              <div className="rounded-lg border bg-background p-3" data-testid="question-trial-result">
                <p className="text-meta text-muted-foreground">{trial.data.label === 'presente' ? 'Presente' : 'Nessuno'} · Prova senza salvataggio</p>
                <p className="mt-2 whitespace-pre-wrap text-body">{String(trial.data.example?.question_text ?? 'Nessun esempio per questa unità.')}</p>
                {Boolean(trial.data.example?.pregenerated_material) && (
                  <p className="mt-2 whitespace-pre-wrap text-body">{String(trial.data.example?.pregenerated_material)}</p>
                )}
              </div>
            )}
          </div>
        </div>
      </SettingsDisclosure>
    </SettingsGroup>
  )
}

export function VoteRulesSettings() {
  const query = useRecallRules()
  const types = useQuestionSettings().data?.types ?? []
  const typeName = (id: string) => QUESTION_TYPE_LABELS[id as keyof typeof QUESTION_TYPE_LABELS] ?? types.find(t => t.id === id)?.nome ?? id
  const settings = useSaveRecallVotes()
  const update = useUpdateRecallRules()
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJobStatus(jobId)
  const finished = jobFinished(job.data)
  const refetch = query.refetch
  useEffect(() => { if (jobId && finished) void refetch() }, [jobId, finished, refetch])
  const data = query.data
  const error = query.error ?? settings.error ?? update.error ?? (job.data?.state === 'failed' ? new Error(job.data.error ?? 'Aggiornamento non riuscito.') : job.error)

  return (
    <SettingsGroup
      id="vote-rules"
      title="Regole imparate dai tuoi voti"
      description="RT usa i tuoi voti nel ripasso per adattare stile, taglio e difficoltà delle domande."
    >
      {error && (
        <div className="px-4 py-3">
          <Alert tone="danger">{errorMessage(error)}</Alert>
        </div>
      )}
      <SettingsSwitch
        id="recall-votes"
        label="Usa i voti per migliorare le domande"
        info="Quando voti una domanda nel ripasso, RT aggiorna le regole della materia per evitare domande fuori tema o poco utili."
        checked={data?.votes_enabled ?? true}
        disabled={settings.isPending}
        onChange={votes_enabled => settings.mutate({ votes_enabled, presave_check: data?.presave_check ?? true })}
      />
      <SettingsSwitch
        id="recall-presave"
        label="Controlla le domande prima di salvarle"
        info="Prima di salvare le domande generate, un controllo verifica che rispettino le regole imparate dai voti."
        checked={data?.presave_check ?? true}
        disabled={settings.isPending}
        onChange={presave_check => settings.mutate({ votes_enabled: data?.votes_enabled ?? true, presave_check })}
      />
      {(data?.groups ?? []).map((group, index) => {
        const label = `${typeName(group.type)}${group.subject ? ` · ${group.subject}` : ''}`
        const summary = `${group.votes} ${group.votes === 1 ? 'voto' : 'voti'}`
        return (
          <SettingsDisclosure key={`${group.type}:${group.subject}`} label={label} summary={summary} defaultOpen={false}>
            <VoteRuleEditor
              id={`recall-rule-${index}`}
              label={label}
              group={group}
              regenerating={update.isPending || Boolean(jobId && !finished)}
              onRegenerate={() => update.mutate({ type: group.type, subject: group.subject, mock: false }, { onSuccess: accepted => setJobId(accepted.job_id) })}
            />
          </SettingsDisclosure>
        )
      })}
    </SettingsGroup>
  )
}

function VoteRuleEditor({
  id,
  label,
  group,
  regenerating,
  onRegenerate,
}: {
  id: string
  label: string
  group: { type: string; subject: string; votes: number; rules: string[]; updated_at?: string | null }
  regenerating: boolean
  onRegenerate: () => void
}) {
  const edit = useEditRecallRules()
  const initialText = group.rules.join('\n')
  const [draft, setDraft] = useState<{ base: string; text: string } | null>(null)
  const text = draft && draft.base === initialText ? draft.text : initialText

  const normalize = (raw: string) => raw.split('\n').map(line => line.trim()).filter(Boolean)
  const autoSave = useAutoSave(edit, text, {
    delay: 600,
    initial: initialText,
    equals: (a, b) => normalize(a).join('\n') === normalize(b).join('\n'),
    serialize: (val) => ({ type: group.type, subject: group.subject, rules: normalize(val) }),
  })

  return (
    <div className="flex flex-col gap-2.5">
      {group.updated_at && (
        <p className="text-meta text-muted-foreground">
          Aggiornate il {new Date(group.updated_at).toLocaleString('it-IT')}
        </p>
      )}
      <Textarea
        id={id}
        aria-label={label}
        rows={3}
        maxLength={16000}
        value={text}
        onChange={e => setDraft({ base: initialText, text: e.target.value })}
        onBlur={autoSave.flush}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button type="button" variant="outline" size="sm" disabled={regenerating} onClick={onRegenerate}>
          <RotateCw aria-hidden />
          Rigenera
        </Button>
        <AutoSaveStatus status={autoSave.status} error={autoSave.error} onRetry={autoSave.retry} />
      </div>
    </div>
  )
}
