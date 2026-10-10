import { expect, it } from 'vitest'
import { paragraphIssue } from './reviewIssues'

it('le nuove verifiche ASR con sostituzione letterale riguardano solo la citazione', () => {
  const issue = { id: 'sci_1', type: 'ERR_ASR_LLM', severity: 'high', claim: 'citazione', reason: 'motivazione' }
  expect(paragraphIssue(issue)).toBe(true)
  expect(paragraphIssue({ ...issue, suggested_fix: 'sostituzione esatta' })).toBe(false)
})
