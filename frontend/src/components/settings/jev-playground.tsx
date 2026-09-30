import { Minus, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, errorMessage, unwrap } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import {
  FALLBACK, OPERATORS, OUTCOMES, PHASES, TEXT_OPERATORS, TYPES, answerFields, defaultCondition, percent as pct,
  type Condition, type Decision, type DecisionTest, type Phase, type QuestionType, type Rule,
} from '@/lib/jev'
import { Field, Section } from './common'

/** Editor della domanda (tipo, testo, opzioni o livelli) e della mappatura verso le etichette RT. */
export function DecisionEditor({ phase, decision, onChange, onTypeChange }: {
  phase: Phase; decision: Decision; onChange: (d: Decision) => void; onTypeChange: (t: QuestionType) => void
}) {
  const options = decision.options ?? []
  const levels = decision.levels ?? []
  const rules = decision.rules ?? []
  const fields = answerFields(decision)
  const setRules = (next: Rule[]) => onChange({ ...decision, rules: next })
  const setRule = (index: number, rule: Rule) => setRules(rules.map((r, i) => (i === index ? rule : r)))
  const setCondition = (ri: number, ci: number, condition: Condition) =>
    setRule(ri, { ...rules[ri], conditions: rules[ri].conditions.map((c, i) => (i === ci ? condition : c)) })
  return <div className="flex flex-col gap-3">
    <Field label="Tipo di domanda" htmlFor="jev-type"><Select id="jev-type" value={decision.type} onChange={(e) => onTypeChange(e.target.value as QuestionType)}>
      {Object.entries(TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </Select></Field>
    <Field label="Domanda" htmlFor="jev-question" hint="Lo stato inviato al classificatore è l’unità di lezione: il testo qui descrive cosa decidere.">
      <textarea id="jev-question" className="w-full rounded border bg-background p-2 text-sm" rows={5} value={decision.question}
        onChange={(e) => onChange({ ...decision, question: e.target.value })} /></Field>

    {decision.type === 'choice' && <fieldset className="flex flex-col gap-2"><legend className="text-sm font-medium">Opzioni</legend>
      {options.map((option, i) => <div key={i} className="grid gap-2 rounded border p-2 sm:grid-cols-[12rem_1fr_auto]" data-testid="jev-option">
        <Input aria-label={`Restituita come (opzione ${i + 1})`} value={option.label} placeholder="etichetta"
          onChange={(e) => onChange({ ...decision, options: options.map((o, j) => (j === i ? { ...o, label: e.target.value } : o)) })} />
        <textarea aria-label={`Scegli quando (opzione ${i + 1})`} className="w-full rounded border bg-background p-2 text-sm" rows={2} value={option.description}
          placeholder="Scegli quando…" onChange={(e) => onChange({ ...decision, options: options.map((o, j) => (j === i ? { ...o, description: e.target.value } : o)) })} />
        <Button variant="ghost" size="icon" aria-label={`Rimuovi opzione ${i + 1}`} disabled={options.length <= 2}
          onClick={() => onChange({ ...decision, options: options.filter((_, j) => j !== i) })}><Trash2 /></Button>
      </div>)}
      <Button variant="outline" size="sm" className="self-start" onClick={() => onChange({ ...decision, options: [...options, { label: '', description: '' }] })}><Plus />Aggiungi opzione</Button>
    </fieldset>}

    {decision.type === 'score' && <fieldset className="flex flex-col gap-2"><legend className="text-sm font-medium">Livelli (dal più basso al più alto)</legend>
      {levels.map((level, i) => <div key={i} className="flex gap-2" data-testid="jev-level">
        <textarea aria-label={`Livello ${i + 1}`} className="w-full rounded border bg-background p-2 text-sm" rows={2} value={level}
          onChange={(e) => onChange({ ...decision, levels: levels.map((l, j) => (j === i ? e.target.value : l)) })} />
        <Button variant="ghost" size="icon" aria-label={`Rimuovi livello ${i + 1}`} disabled={levels.length <= 1}
          onClick={() => onChange({ ...decision, levels: levels.filter((_, j) => j !== i) })}><Trash2 /></Button>
      </div>)}
      <Button variant="outline" size="sm" className="self-start" onClick={() => onChange({ ...decision, levels: [...levels, ''] })}><Plus />Aggiungi livello</Button>
    </fieldset>}

    <fieldset className="flex flex-col gap-2 border-t pt-3"><legend className="text-sm font-medium">Mappatura verso le etichette RT</legend>
      <p className="text-xs text-muted-foreground">Le regole sono valutate in ordine: vale la prima vera. Se nessuna è vera l’unità {phase === 'relevance' ? 'resta inclusa' : 'va comunque in review'}.</p>
      {rules.map((rule, ri) => <div key={ri} className="flex flex-col gap-2 rounded border p-2" data-testid="jev-rule">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>Etichetta</span>
          <Input aria-label={`Etichetta (regola ${ri + 1})`} className="w-44" value={rule.label} onChange={(e) => setRule(ri, { ...rule, label: e.target.value })} />
          <span>→</span>
          <Select aria-label={`Esito RT (regola ${ri + 1})`} className="w-56" value={rule.outcome} onChange={(e) => setRule(ri, { ...rule, outcome: e.target.value })}>
            {Object.entries(OUTCOMES[phase]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
          <Select aria-label={`Combina condizioni (regola ${ri + 1})`} className="w-48" value={rule.match ?? 'all'} onChange={(e) => setRule(ri, { ...rule, match: e.target.value as Rule['match'] })}>
            <option value="all">Tutte le condizioni</option><option value="any">Almeno una</option>
          </Select>
          <Button variant="ghost" size="icon" aria-label={`Rimuovi regola ${ri + 1}`} onClick={() => setRules(rules.filter((_, i) => i !== ri))}><Trash2 /></Button>
        </div>
        {rule.conditions.map((condition, ci) => {
          const kind = fields.find((f) => f.value === condition.field)
          const text = kind?.text ?? false
          return <div key={ci} className="flex flex-wrap items-center gap-2 pl-4 text-sm" data-testid="jev-condition">
            <span>{ci === 0 ? 'quando' : rule.match === 'any' ? 'oppure' : 'e'}</span>
            <Select aria-label={`Campo (regola ${ri + 1}, condizione ${ci + 1})`} className="w-48" value={condition.field}
              onChange={(e) => {
                const next = fields.find((f) => f.value === e.target.value)
                setCondition(ri, ci, next?.text
                  ? { field: e.target.value, op: 'eq', value: options[0]?.label ?? '' }
                  : { field: e.target.value, op: text ? 'gte' : condition.op, value: text ? 0.5 : condition.value })
              }}>
              {!kind && <option value={condition.field}>{condition.field} (non valido)</option>}
              {fields.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </Select>
            <Select aria-label={`Operatore (regola ${ri + 1}, condizione ${ci + 1})`} className="w-48" value={condition.op}
              onChange={(e) => setCondition(ri, ci, { ...condition, op: e.target.value as Condition['op'] })}>
              {(text ? TEXT_OPERATORS : (Object.keys(OPERATORS) as Condition['op'][])).map((op) => <option key={op} value={op}>{OPERATORS[op]}</option>)}
            </Select>
            {text
              ? <Select aria-label={`Valore (regola ${ri + 1}, condizione ${ci + 1})`} className="w-44" value={String(condition.value)}
                  onChange={(e) => setCondition(ri, ci, { ...condition, value: e.target.value })}>
                  {!options.some((o) => o.label === condition.value) && <option value={String(condition.value)}>{String(condition.value)}</option>}
                  {options.map((o) => <option key={o.label} value={o.label}>{o.label}</option>)}
                </Select>
              : <Input aria-label={`Valore (regola ${ri + 1}, condizione ${ci + 1})`} className="w-28" type="number" step="0.01" value={condition.value}
                  onChange={(e) => setCondition(ri, ci, { ...condition, value: e.target.value === '' ? '' : Number(e.target.value) })} />}
            <Button variant="ghost" size="icon" aria-label={`Rimuovi condizione ${ci + 1} (regola ${ri + 1})`} disabled={rule.conditions.length <= 1}
              onClick={() => setRule(ri, { ...rule, conditions: rule.conditions.filter((_, i) => i !== ci) })}><Minus /></Button>
            {ci === rule.conditions.length - 1 && <Button variant="ghost" size="icon" aria-label={`Aggiungi condizione (regola ${ri + 1})`}
              onClick={() => setRule(ri, { ...rule, conditions: [...rule.conditions, defaultCondition(decision)] })}><Plus /></Button>}
          </div>
        })}
      </div>)}
      <Button variant="outline" size="sm" className="self-start"
        onClick={() => setRules([...rules, { label: '', outcome: Object.keys(OUTCOMES[phase]).find((o) => o !== FALLBACK[phase]) ?? FALLBACK[phase], match: 'all', conditions: [defaultCondition(decision)] }])}>
        <Plus />Aggiungi etichetta</Button>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>Se nessuna regola è vera: etichetta</span>
        <Input aria-label="Etichetta se nessuna regola è vera" className="w-44" value={decision.fallback_label}
          onChange={(e) => onChange({ ...decision, fallback_label: e.target.value })} />
        <span>→ {OUTCOMES[phase][FALLBACK[phase]]}</span>
      </div>
    </fieldset>
  </div>
}

/** Esito della prova: etichetta RT, risposta del classificatore (tutte le probabilità) e JSON grezzo. */
export function DecisionTestResult({ phase, result }: { phase: Phase; result: DecisionTest }) {
  const answer = result.answer as Record<string, unknown>
  const probabilities = (answer.probabilities ?? {}) as Record<string, number>
  const legend = (answer.legend ?? {}) as Record<string, string>
  const chosen = answer.type === 'choice' ? String(answer.choice) : answer.type === 'score' ? String(answer.score) : null
  return <div className="flex flex-col gap-2 rounded border p-3 text-sm" data-testid="jev-result">
    <div className="flex flex-wrap items-center gap-2">
      <span>Etichetta RT:</span>
      <Badge tone={result.outcome === FALLBACK[phase] ? 'neutral' : 'warning'}>{result.label}</Badge>
      <span className="text-muted-foreground">{OUTCOMES[phase][result.outcome] ?? result.outcome}{result.rule == null ? ' · nessuna regola vera' : ` · regola ${result.rule + 1}`}</span>
    </div>
    <p className="text-xs text-muted-foreground">Unità: {result.unit_id ? `${result.unit_id} · ` : ''}{result.unit_title}</p>
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {answer.type === 'choice' && <><dt>Scelta</dt><dd className="font-medium">{String(answer.choice)}</dd></>}
      {answer.type === 'score' && <><dt>Punteggio</dt><dd className="font-medium">{String(answer.score)}</dd></>}
      {answer.type === 'noul' && <><dt>Probabilità (noul)</dt><dd className="font-medium">{pct(answer.noul)}</dd></>}
      {answer.confidence != null && <><dt>Confidenza</dt><dd>{pct(answer.confidence)}</dd></>}
    </dl>
    {Object.keys(probabilities).length > 0 && <table className="w-full text-left text-xs"><caption className="text-left font-medium">Probabilità per {answer.type === 'score' ? 'livello' : 'etichetta'}</caption>
      <tbody>{Object.entries(probabilities).map(([key, value]) => <tr key={key} className={key === chosen ? 'font-semibold' : undefined}>
        <th className="pr-2 font-normal">{key}{legend[key] ? ` · ${legend[key]}` : ''}</th>
        <td className="w-1/2"><div className="h-2 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} /></div></td>
        <td className="pl-2 text-right">{pct(value)}</td>
      </tr>)}</tbody></table>}
    {Object.keys(legend).length > 0 && Object.keys(probabilities).length === 0 && <ul className="text-xs">
      {Object.entries(legend).map(([key, text]) => <li key={key}><strong>{key}</strong>: {text}</li>)}</ul>}
    <details><summary className="cursor-pointer text-xs">JSON del classificatore</summary>
      <pre className="mt-1 max-h-64 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(result.response, null, 2)}</pre>
    </details>
  </div>
}

/** Lezione e unità su cui provare la configurazione; senza lezione si usa l'unità di esempio. */
function UnitPicker({ lessonId, unitId, onChange }: { lessonId: number | null; unitId: string | null; onChange: (lesson: number | null, unit: string | null) => void }) {
  const lessons = useLessons()
  const units = useQuery({
    queryKey: ['relevance', lessonId],
    enabled: lessonId != null,
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/relevance', { params: { path: { lesson_id: lessonId as number } } })),
  })
  return <div className="grid gap-2 sm:grid-cols-2">
    <Field label="Lezione di prova" htmlFor="jev-lesson"><Select id="jev-lesson" value={lessonId ?? ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null, null)}>
      <option value="">Unità di esempio</option>
      {(lessons.data ?? []).map((l) => <option key={l.id} value={l.id}>{l.titolo || l.folder_name}</option>)}
    </Select></Field>
    <Field label="Unità" htmlFor="jev-unit"><Select id="jev-unit" value={unitId ?? ''} disabled={lessonId == null} onChange={(e) => onChange(lessonId, e.target.value || null)}>
      <option value="">{lessonId == null ? 'Esempio predefinito' : 'Prima unità'}</option>
      {(units.data?.units ?? []).map((u) => <option key={u.unit_id} value={u.unit_id}>{u.unit_id} · {u.title}</option>)}
    </Select></Field>
  </div>
}

type Drafts = Partial<Record<Phase, Decision>>

export function DecisionModelSection() {
  const client = useQueryClient()
  const configured = useQuery({ queryKey: ['decision-model'], queryFn: () => unwrap(api.GET('/api/v1/settings/decision-model')) })
  const [phase, setPhase] = useState<Phase>('relevance')
  const [drafts, setDrafts] = useState<Drafts>({})
  const [modelDraft, setModel] = useState<string | null>(null)
  const [relevanceModelDraft, setRelevanceModel] = useState<string | null>(null)
  const [credentialDraft, setCredential] = useState<string | null>(null)
  const [shadowDraft, setShadow] = useState<boolean | null>(null)
  const [enabledDraft, setEnabled] = useState<boolean | null>(null)
  const [relevanceModeDraft, setRelevanceMode] = useState<'disabled' | 'shadow' | 'active' | null>(null)
  const [target, setTarget] = useState<{ lesson: number | null; unit: string | null }>({ lesson: null, unit: null })
  const data = configured.data
  const model = modelDraft ?? data?.model ?? ''
  const relevanceModel = relevanceModelDraft ?? data?.relevance_model ?? ''
  const credential = credentialDraft ?? data?.credential ?? 'openrouter'
  const shadow = shadowDraft ?? data?.shadow ?? true
  const enabled = enabledDraft ?? data?.enabled ?? false
  const relevanceMode = relevanceModeDraft ?? data?.relevance_mode ?? 'shadow'
  const decisionFor = (p: Phase) => drafts[p] ?? (p === 'relevance' ? data?.relevance_decision : data?.prefilter_decision)
  const decision = decisionFor(phase)
  const phaseModel = phase === 'relevance' ? relevanceModel : model
  const setDecision = (d: Decision) => setDrafts((prev) => ({ ...prev, [phase]: d }))

  const test = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/settings/decision-model/test', {
      body: { phase, decision: decision as Decision, model: phaseModel, credential, lesson_id: target.lesson, unit_id: target.unit },
    })),
  })
  const save = useMutation({
    mutationFn: () => unwrap(api.PUT('/api/v1/settings/decision-model', {
      body: {
        model, relevance_model: relevanceModel, credential, enabled, shadow, relevance_mode: relevanceMode,
        threshold: data?.threshold ?? 0.85, relevance_prompt: data?.relevance_prompt ?? '', relevance_threshold: data?.relevance_threshold ?? 0.85,
        prefilter_prompt: data?.prefilter_prompt ?? '', prefilter_type: data?.prefilter_type ?? 'choice',
        relevance_decision: decisionFor('relevance'), prefilter_decision: decisionFor('prefilter'),
      },
    })),
    onSuccess: (saved) => { client.setQueryData(['decision-model'], saved); setDrafts({}) },
  })
  const customized = phase === 'relevance' ? data?.relevance_customized : data?.prefilter_customized

  return <Section id="classificatore" title="Classificatore"
    description="Configura la domanda inviata al classificatore (ad esempio Jev) per ogni fase e come la risposta diventa un’etichetta di RT. Un errore o una risposta non valutabile lasciano sempre passare l’unità.">
    {configured.isError && <Alert tone="danger">{errorMessage(configured.error)}</Alert>}
    <div className="grid gap-2 sm:grid-cols-2">
      <Field label="Fase" htmlFor="jev-phase"><Select id="jev-phase" value={phase} onChange={(e) => { setPhase(e.target.value as Phase); test.reset() }}>
        {Object.entries(PHASES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </Select></Field>
      <Field label="Credenziale" htmlFor="decision-model-credential"><Input id="decision-model-credential" value={credential} onChange={(e) => setCredential(e.target.value)} /></Field>
    </div>
    {phase === 'relevance'
      ? <div className="grid gap-2 sm:grid-cols-2">
          <Field label="Modello del classificatore di rilevanza" htmlFor="relevance-model-name"><Input id="relevance-model-name" value={relevanceModel} onChange={(e) => setRelevanceModel(e.target.value)} placeholder="Facoltativo: ID del modello classificatore" /></Field>
          <Field label="Comportamento del classificatore" htmlFor="relevance-mode"><Select id="relevance-mode" value={relevanceMode} onChange={(e) => setRelevanceMode(e.target.value as typeof relevanceMode)}>
            <option value="disabled">Disattivato · tutte le unità passano, nessuna chiamata</option>
            <option value="shadow">Ombra · classifica, tutte le unità passano</option>
            <option value="active">Filtro attivo · solo unità didattiche a review e Recall</option>
          </Select></Field>
        </div>
      : <div className="flex flex-col gap-2">
          <Field label="Modello del prefiltro errori" htmlFor="decision-model-name"><Input id="decision-model-name" value={model} onChange={(e) => setModel(e.target.value)} placeholder="Facoltativo: ID del modello classificatore" /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />Abilita il prefiltro errori</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={shadow} onChange={(e) => setShadow(e.target.checked)} />Prefiltro in ombra (non salta la review)</label>
        </div>}
    {decision && data && <>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge tone={customized || drafts[phase] ? 'warning' : 'neutral'}>{drafts[phase] ? 'Modifiche non salvate' : customized ? 'Domanda personalizzata' : 'Domanda predefinita'}</Badge>
      </div>
      <DecisionEditor phase={phase} decision={decision} onChange={setDecision}
        onTypeChange={(type) => setDecision(data.templates[phase]?.[type] ?? { ...decision, type })} />
      <div className="border-t pt-3"><UnitPicker lessonId={target.lesson} unitId={target.unit} onChange={(lesson, unit) => setTarget({ lesson, unit })} /></div>
    </>}
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={!decision || !phaseModel.trim() || test.isPending} onClick={() => test.mutate()}>{test.isPending ? 'Prova in corso…' : 'Prova configurazione'}</Button>
      <Button variant="ghost" disabled={!data} onClick={() => data && setDecision(data.templates[phase][phase === 'relevance' ? 'choice' : data.prefilter_type])}>Ripristina predefinita</Button>
      <Button disabled={save.isPending || (enabled && !model.trim())} onClick={() => save.mutate()}>Salva</Button>
    </div>
    {!phaseModel.trim() && <p className="text-xs text-muted-foreground">Indica il modello della fase per provare la configurazione.</p>}
    {test.isError && <Alert tone="danger">{errorMessage(test.error)}</Alert>}
    {test.isSuccess && <DecisionTestResult phase={phase} result={test.data} />}
    {save.isError && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
    {save.isSuccess && <p role="status" className="text-xs text-success">Salvato.</p>}
  </Section>
}
