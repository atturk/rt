import type { Schemas } from '@/api/client'

/** Domande del classificatore per fase e mappatura verso le etichette RT (vedi rt/core/jev_decision.py). */
export type Decision = Schemas['JevDecisionConfig']
export type Rule = Schemas['JevRule']
export type Condition = Schemas['JevCondition']
export type DecisionTest = Schemas['DecisionTestOut']
export type Phase = 'relevance' | 'prefilter'
export type QuestionType = Decision['type']

export const PHASES: Record<Phase, string> = {
  relevance: 'Rilevanza delle unità (gate di review e Recall)',
  prefilter: 'Prefiltro errori (prima della review)',
}
/** Esiti di RT su cui ogni etichetta deve ricadere; quello di FALLBACK vale quando nessuna regola è vera. */
export const OUTCOMES: Record<Phase, Record<string, string>> = {
  relevance: { didactic: 'Includi · didattica', organizational: 'Escludi · organizzativa', no_content: 'Escludi · senza contenuto' },
  prefilter: { skip_review: 'Salta la review', needs_review: 'Esegui la review' },
}
export const FALLBACK: Record<Phase, string> = { relevance: 'didactic', prefilter: 'needs_review' }
export const TYPES: Record<QuestionType, string> = {
  choice: 'choice · scelta tra opzioni',
  noul: 'noul · probabilità che l’affermazione sia vera',
  score: 'score · punteggio su livelli ordinati',
}
export const OPERATORS: Record<Condition['op'], string> = {
  eq: 'è uguale a', ne: 'è diverso da', gt: 'è maggiore di', gte: 'è maggiore o uguale a', lt: 'è minore di', lte: 'è minore o uguale a',
}
export const TEXT_OPERATORS: Condition['op'][] = ['eq', 'ne']

export type AnswerField = { value: string; label: string; text: boolean }

/** Campi della risposta confrontabili nelle regole: noul ha solo la probabilità, choice e score anche la confidenza. */
export function answerFields(decision: Decision): AnswerField[] {
  if (decision.type === 'choice') {
    return [
      { value: 'choice', label: 'scelta', text: true },
      { value: 'confidence', label: 'confidenza', text: false },
      ...(decision.options ?? []).map((o) => ({ value: `p:${o.label}`, label: `probabilità di ${o.label || '…'}`, text: false })),
    ]
  }
  if (decision.type === 'score') return [{ value: 'score', label: 'punteggio', text: false }, { value: 'confidence', label: 'confidenza', text: false }]
  return [{ value: 'noul', label: 'probabilità (noul)', text: false }]
}

export function defaultCondition(decision: Decision): Condition {
  const [first] = answerFields(decision)
  return first.text ? { field: first.value, op: 'eq', value: decision.options?.[0]?.label ?? '' } : { field: first.value, op: 'gte', value: 0.5 }
}

export const percent = (value: unknown) => (typeof value === 'number' ? `${Math.round(value * 1000) / 10}%` : String(value ?? '—'))
