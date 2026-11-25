/** Argomenti della lezione, uno per voce. Il build li salva in info.yaml uniti da ", ":
 *  se il testo è proprio quello, si usano le voci generate, così le virgole interne restano. */
export function lessonTopics(argomenti: string | null | undefined, generated: string[] = []): string[] {
  const text = (argomenti ?? '').trim()
  const items = !text || (generated.length && text === generated.join(', ').trim()) ? generated : text.split(/[,;\n]/)
  return unique(items)
}

/** Argomenti e poi le keywords di tutte le unità, una voce per riga, senza doppioni. */
export function topicsAndKeywordsText(topics: string[], units: { key_concepts?: string[] | null }[]): string {
  return unique([...topics, ...units.flatMap(unit => unit.key_concepts ?? [])]).join('\n')
}

function unique(items: string[]): string[] {
  const result: string[] = []
  for (const item of items) {
    const value = item.trim()
    if (value && !result.includes(value)) result.push(value)
  }
  return result
}
