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
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Checkbox, Field, Section, SettingsSelect } from './common'

const empty: QuestionDefinition = { id: '', nome: '', icona: 'MessageSquare', materie: [], cerca: '', anche_adatti: false, continua: false, chiedi: '', correzione: 'testo', varianti: false }
const textarea = 'w-full rounded-md border border-input bg-card px-3 py-2 text-body focus-visible:outline-2 focus-visible:outline-ring'

export function QuestionsSettingsSection() {
  const query = useQuestionSettings()
  if (query.isError) return <Alert tone="danger">{errorMessage(query.error)}</Alert>
  return query.data ? <QuestionsSettings data={query.data} /> : <p className="text-body">Carico i tipi di domanda…</p>
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
  return <div className="flex flex-col divide-y">
    <Section id="question-types" title="Tipi personalizzati">
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => { setEditor({ definition: { ...empty } }); setNotice(null); save.reset() }}><Plus aria-hidden />Nuovo tipo</Button>
        <Button variant="outline" disabled={importing.isPending} onClick={() => file.current?.click()}><Upload aria-hidden />Importa</Button>
        <input ref={file} type="file" accept=".json,application/json" aria-label="Importa tipo JSON" className="sr-only" onChange={event => void importFile(event.target.files?.[0])} />
      </div>
      {data.types.length === 0 && <p className="text-body text-muted-foreground">Nessun tipo personalizzato.</p>}
      <ul className="divide-y">
        {data.types.map(type => <li key={type.id} className="flex flex-wrap items-center gap-3 py-3" data-testid={`question-type-${type.id}`}>
          <TypeIcon name={type.icona} /><div className="min-w-0 flex-1"><p className="text-body font-semibold">{type.nome}</p><p className="text-meta text-muted-foreground">{type.materie.join(', ')}</p></div>
          <IconButton label={`Modifica ${type.nome}`} icon={Pencil} onClick={() => { setEditor({ definition: { ...empty, ...type }, id: type.id }); save.reset() }} />
          <IconButton label={`Esporta ${type.nome}`} icon={Download} onClick={() => { void exportQuestionType(type.id ?? '').catch(failure => setError(errorMessage(failure))) }} />
          <IconButton label={`Elimina ${type.nome}`} icon={Trash2} onClick={() => setDeleting(type)} />
        </li>)}
      </ul>
      {notice && <p role="status" className="text-meta text-success">{notice}</p>}
      {(error || importing.isError || remove.isError) && <Alert tone="danger">{error ?? errorMessage(importing.error ?? remove.error)}</Alert>}
    </Section>
    <VoteRulesSettings />
    <Section id="question-gallery" title="Galleria dei modelli pronti">
      <details><summary className="cursor-pointer text-body">Scegli un modello da copiare</summary>
        <ul className="mt-3 grid gap-3 sm:grid-cols-2">{data.templates.map(template => <li key={template.id} className="flex items-center gap-3 rounded-md border p-3">
          <TypeIcon name={template.icona} /><span className="flex-1 text-body">{template.nome}</span>
          <Button size="sm" variant="outline" aria-label={`Usa ${template.nome}`} onClick={() => { setEditor({ definition: { ...empty, ...template, id: '', materie: [], correzione: template.correzione as QuestionDefinition['correzione'] } }); save.reset() }}>Usa</Button>
        </li>)}</ul>
      </details>
    </Section>
    {editor && <QuestionTypeEditor key={`${editor.id ?? 'new'}:${editor.definition.nome}`} initial={editor.definition} existing={Boolean(editor.id)} subjects={Array.isArray(subjectsQuery.data) ? subjectsQuery.data.map((s) => s.nome) : data.materie} onSave={submit} onCancel={() => setEditor(null)} pending={save.isPending} error={save.error ? errorMessage(save.error) : null} />}
    <ConfirmDialog open={Boolean(deleting)} title="Elimina tipo" confirmLabel="Elimina" onCancel={() => setDeleting(null)} confirmDisabled={remove.isPending}
      onConfirm={() => { if (deleting?.id) remove.mutate(deleting.id, { onSuccess: () => { setDeleting(null); setEditor(null) } }) }}>
      Le domande già generate resteranno nello storico.
    </ConfirmDialog>
  </div>
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
  const selectedLessons = (lessons.data ?? []).filter(lesson => draft.materie.some(materia => materia.toLocaleLowerCase() === lesson.materia.toLocaleLowerCase()))
  const valid = draft.nome.trim() && draft.cerca.trim() && draft.chiedi.trim() && draft.materie.length > 0
  const trialDefinition = () => ({ ...draft })
  function submit(event: FormEvent) { event.preventDefault(); onSave(trialDefinition()) }
  return <Section id="question-editor" title={existing ? 'Modifica tipo' : 'Nuovo tipo'}>
    <form onSubmit={submit} className="flex flex-col">
      <Field label="Nome" htmlFor="question-name" hint="Il nome compare nei controlli Genera e nel ripasso."><Input id="question-name" required maxLength={100} value={draft.nome} onChange={event => set('nome', event.target.value)} /></Field>
      <Field label="Identificativo" htmlFor="question-id" hint="Nasce dal nome al salvataggio e resta stabile quando il nome cambia."><Input id="question-id" readOnly value={draft.id || 'Generato dal nome'} /></Field>
      <Field label="Icona" htmlFor="question-icon" hint="Scegli l’icona che accompagna il nome del tipo."><div className="flex items-center gap-2"><TypeIcon name={draft.icona} /><SettingsSelect id="question-icon" value={draft.icona} onChange={event => set('icona', event.target.value)}>{Array.from(new Set([...TYPE_ICON_NAMES, draft.icona ?? 'MessageSquare'])).map(icon => <option key={icon} value={icon}>{icon}</option>)}</SettingsSelect></div></Field>
      <Field label="Materie" htmlFor="question-subjects" hint="Il tipo è disponibile soltanto nelle materie selezionate."><fieldset id="question-subjects" className="flex flex-wrap gap-3"><legend className="sr-only">Materie</legend>{Array.from(new Set([...subjects, ...draft.materie])).map(subject => <label key={subject} className="flex items-center gap-2 text-body"><input type="checkbox" checked={draft.materie.includes(subject)} onChange={event => set('materie', event.target.checked ? [...draft.materie, subject] : draft.materie.filter(m => m !== subject))} />{subject}</label>)}</fieldset></Field>
      <Field label="Cerca" htmlFor="question-find" hint="Descrivi ciò che il classificatore deve riconoscere nella lezione."><textarea id="question-find" required maxLength={12000} rows={3} className={textarea} value={draft.cerca} onChange={event => set('cerca', event.target.value)} /></Field>
      <Field label="Anche contenuti adatti" htmlFor="question-adapt" hint="Include contenuti che si prestano al tipo anche senza un esempio esplicito."><input id="question-adapt" type="checkbox" checked={draft.anche_adatti ?? false} onChange={event => set('anche_adatti', event.target.checked)} className="self-start" /></Field>
      <Field label="Unità consecutive" htmlFor="question-continue" hint="Due unità consecutive marcate vengono inviate insieme al generatore."><input id="question-continue" type="checkbox" checked={draft.continua ?? false} onChange={event => set('continua', event.target.checked)} className="self-start" /></Field>
      <Field label="Chiedi" htmlFor="question-instructions" hint="Indica come scrivere una domanda; la risposta dello studente è sempre testuale."><textarea id="question-instructions" required maxLength={24000} rows={5} className={textarea} value={draft.chiedi} onChange={event => set('chiedi', event.target.value)} /></Field>
      <Field label="Correzione" htmlFor="question-correction" hint="La valutazione usa la soluzione generata oppure il testo delle subunità."><SettingsSelect id="question-correction" value={draft.correzione} onChange={event => set('correzione', event.target.value as QuestionDefinition['correzione'])}><option value="testo">Testo della lezione</option><option value="soluzione">Soluzione attesa</option></SettingsSelect></Field>
      <Field label="Varianti verificate" htmlFor="question-variants" hint="Permette nuove varianti, controllate in modo indipendente prima di proporle."><input id="question-variants" type="checkbox" checked={draft.varianti ?? false} onChange={event => set('varianti', event.target.checked)} className="self-start" /></Field>
      <div className="mt-3 flex gap-2"><Button type="submit" disabled={pending || !valid}>Salva tipo</Button><Button variant="outline" disabled={pending} onClick={onCancel}>Annulla</Button></div>
      {error && <Alert tone="danger" className="mt-3">{error}</Alert>}
    </form>
    <details className="mt-5"><summary className="cursor-pointer text-body font-semibold">Prova su un’unità</summary>
      <div className="mt-3 flex flex-col gap-3">
        <Field label="Lezione" htmlFor="question-trial-lesson"><SettingsSelect id="question-trial-lesson" value={lessonId} onChange={event => { setLessonId(Number(event.target.value)); setUnitId(''); trial.reset() }}><option value={0}>Scegli una lezione</option>{selectedLessons.map(lesson => <option key={lesson.id} value={lesson.id}>{lesson.titolo || lesson.folder_name}</option>)}</SettingsSelect></Field>
        <Field label="Unità" htmlFor="question-trial-unit"><SettingsSelect id="question-trial-unit" value={unitId} onChange={event => { setUnitId(event.target.value); trial.reset() }}><option value="">Scegli un’unità</option>{(study.data?.units ?? []).map(unit => <option key={unit.id} value={unit.id}>{unit.id} · {unit.title}</option>)}</SettingsSelect></Field>
        {(lessons.isError || study.isError) && <Alert tone="danger">{errorMessage(lessons.error ?? study.error)}</Alert>}
        <Button className="self-start" disabled={!valid || !lessonId || !unitId || trial.isPending} onClick={() => trial.mutate({ definition: trialDefinition(), lesson_id: lessonId, unit_id: unitId, mock: false })}>{trial.isPending ? 'Provo…' : 'Prova'}</Button>
        {trial.isError && <Alert tone="danger">{errorMessage(trial.error)}</Alert>}
        {trial.data && <div className="rounded-md border p-3" data-testid="question-trial-result"><p className="text-meta text-muted-foreground">{trial.data.label === 'presente' ? 'Presente' : 'Nessuno'} · Prova senza salvataggio</p><p className="mt-2 whitespace-pre-wrap text-body">{String(trial.data.example?.question_text ?? 'Nessun esempio per questa unità.')}</p>{Boolean(trial.data.example?.pregenerated_material) && <p className="mt-2 whitespace-pre-wrap text-body">{String(trial.data.example?.pregenerated_material)}</p>}</div>}
      </div>
    </details>
  </Section>
}


export function VoteRulesSettings() {
  const query = useRecallRules()
  const settings = useSaveRecallVotes()
  const edit = useEditRecallRules()
  const update = useUpdateRecallRules()
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobFailure, setJobFailure] = useState<string | null>(null)
  const job = useJobStatus(jobId)
  const finished = jobFinished(job.data)
  const refetch = query.refetch
  useEffect(() => { if (jobId && finished) { if (job.data?.state === 'failed') setJobFailure(job.data.error ?? 'Aggiornamento non riuscito.'); void refetch(); setJobId(null) } }, [jobId, finished, refetch, job.data])
  const data = query.data
  const error = query.error ?? settings.error ?? edit.error ?? update.error ?? (jobFailure ? new Error(jobFailure) : null) ?? (job.data?.state === 'failed' ? new Error(job.data.error ?? 'Aggiornamento non riuscito.') : job.error)
  return <Section id="vote-rules" title="Regole dai voti">
    {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
    <Checkbox id="recall-votes" label="Voti" checked={data?.votes_enabled ?? true} disabled={settings.isPending} onChange={votes_enabled => settings.mutate({ votes_enabled, presave_check: data?.presave_check ?? true })} />
    <Checkbox id="recall-presave" label="Controllo prima di salvare" checked={data?.presave_check ?? true} disabled={settings.isPending} onChange={presave_check => settings.mutate({ votes_enabled: data?.votes_enabled ?? true, presave_check })} />
    {(data?.groups ?? []).map((group, index) => <div key={`${group.type}:${group.subject}`} className="flex flex-col gap-2 border-t py-3">
      <div className="flex items-center gap-2"><label htmlFor={`recall-rule-${index}`} className="flex-1 text-body font-semibold">{group.type} · {group.subject || 'Senza materia'}</label>
        <IconButton icon={RotateCw} label="Aggiorna ora" disabled={update.isPending || Boolean(jobId)} onClick={() => update.mutate({ type: group.type, subject: group.subject }, { onSuccess: accepted => setJobId(accepted.job_id) })} />
      </div>
      <p className="text-meta text-muted-foreground">{group.votes} voti{group.updated_at ? ` · ${new Date(group.updated_at).toLocaleString('it-IT')}` : ''}</p>
      <textarea id={`recall-rule-${index}`} key={group.rules.join('\n')} defaultValue={group.rules.join('\n')} rows={3} maxLength={16000} className={textarea} onBlur={event => {
        const rules = event.target.value.split('\n').map(line => line.trim()).filter(Boolean)
        if (rules.join('\n') !== group.rules.join('\n')) edit.mutate({ type: group.type, subject: group.subject, rules })
      }} />
    </div>)}
  </Section>
}
