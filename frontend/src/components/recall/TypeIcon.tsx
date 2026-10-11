import { BookOpen, Brain, Calculator, Code, Database, History, ListChecks, ListTree, MessageSquare, Sigma, Stethoscope } from 'lucide-react'

const icons = { BookOpen, Brain, Calculator, Code, Database, History, ListChecks, ListTree, MessageSquare, Sigma, Stethoscope }

/** Il nome dell'icona arriva dal registro; i nomi sconosciuti usano l'icona di domanda. */
export function TypeIcon({ name }: { name?: string | null }) {
  const Icon = icons[name as keyof typeof icons] ?? MessageSquare
  return <Icon className="size-4 shrink-0" aria-hidden />
}
