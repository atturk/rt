export type DiffPart = { type: 'same' | 'removed' | 'added'; text: string }

/** Diff per parole (LCS) tra il testo originale e la correzione proposta. */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = before.split(/(\s+)/).filter(Boolean)
  const b = after.split(/(\s+)/).filter(Boolean)
  if (a.length * b.length > 250_000) {
    return [
      { type: 'removed', text: before },
      { type: 'added', text: after },
    ]
  }
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  const parts: DiffPart[] = []
  const push = (type: DiffPart['type'], text: string) => {
    const last = parts[parts.length - 1]
    if (last && last.type === type) last.text += text
    else parts.push({ type, text })
  }
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push('same', a[i])
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) push('removed', a[i++])
    else push('added', b[j++])
  }
  while (i < a.length) push('removed', a[i++])
  while (j < b.length) push('added', b[j++])
  return parts
}
