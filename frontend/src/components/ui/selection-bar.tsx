import type { ReactNode } from 'react'

/** Barra condivisa da Archivio e selezione dei media. */
export function SelectionBar({ count, children }: { count: string; children: ReactNode }) {
  return <div role="toolbar" aria-label="Selezione" className="inline-flex items-center gap-1 rounded-[10px] border bg-white px-[6px] py-1 shadow-sm [--control-size:32px] dark:bg-card">
    <span className="px-2 text-xs text-muted-foreground">{count}</span>{children}
  </div>
}
