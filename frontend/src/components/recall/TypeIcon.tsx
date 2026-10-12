import { MessageSquare } from 'lucide-react'
import { icons } from '@/lib/typeIcons'

/** Il nome dell'icona arriva dal registro; i nomi sconosciuti usano l'icona di domanda. */
export function TypeIcon({ name, className = 'size-4 shrink-0' }: { name?: string | null; className?: string }) {
  const Icon = icons[name as keyof typeof icons] ?? MessageSquare
  return <Icon className={className} aria-hidden />
}
