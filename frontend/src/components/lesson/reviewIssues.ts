import { AudioLines, GitCompareArrows } from 'lucide-react'
import type { Schemas } from '@/api/client'

export type IssueItem = Schemas['IssueItem']
export type Issue = { id: string; type: string; severity: string; unit_id?: string | null; claim: string; reason: string; suggested_fix?: string | null; source_quote?: string | null; unanchored?: boolean; literal_replacement?: boolean; anchor?: Schemas['Anchor'] | null }
export const issueOf = (item: IssueItem) => item.issue as unknown as Issue
export const paragraphIssue = (issue: Issue) => ['ERR_ASR_ST', 'ERR_REWRITE_DRIFT'].includes(issue.type) || issue.type === 'ERR_ASR_LLM' && !issue.literal_replacement
export const issueLabels: Record<string, string> = {
  ERR_CONCETTUALE: 'Errore concettuale', ERR_REWRITE_DRIFT: 'Fedeltà al parlato', ERR_ASR_LLM: 'Qualità ASR · modello',
  ERR_ASR_ST: 'Qualità ASR · statistica', IMPRECISIONE: 'Imprecisione', OMISSIONE: 'Omissione', CHIARIMENTO: 'Chiarimento',
}
export const paragraphIssueIcon = (issue: Issue) => issue.type === 'ERR_REWRITE_DRIFT' ? GitCompareArrows : AudioLines
export const decisionLabels: Record<string, string> = { accepted: 'accettata', rejected: 'mantenuta', edited: 'modificata' }
