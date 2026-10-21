import { useEffect, useRef } from 'react'

import { DELIMITED, renderDelimitedMath } from '@/lib/math'

/**
 * Testo semplice con formule fra delimitatori ($…$, \(…\), $$…$$, \[…\]), come nelle domande.
 * Le formule si rendono dopo il montaggio; la chiave sul testo rimonta lo span quando cambia, così
 * React non aggiorna nodi di testo già sostituiti dal MathML.
 */
export function MathText({ text, className }: { text: string; className?: string }) {
  return <MathSpan key={text} text={text} className={className} />
}

function MathSpan({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (ref.current && text.search(DELIMITED) >= 0) void renderDelimitedMath(ref.current)
  }, [text])
  return <span ref={ref} className={className}>{text}</span>
}
