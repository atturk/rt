import { useState } from 'react'
import { TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'
import { useMissingLessons } from '@/api/calendar'
import { IconButton } from '@/components/ui/icon-button'
import { Modal } from '@/components/ui/modal'
import { usePreference } from '@/lib/preferences'

export function MissingLessonsButton({ materia }: { materia: string }) {
  const [enabled] = usePreference('calendar.missingWarning', true)
  const missing = useMissingLessons(enabled)
  const [open, setOpen] = useState(false)
  const items = missing.data?.subjects?.find(s => s.materia.trim().toUpperCase() === materia.trim().toUpperCase())?.missing ?? []
  if (!enabled || !items.length) return null
  return <>
    <IconButton icon={TriangleAlert} label={`${items.length} lezioni mancanti`} className="size-5 min-h-5 min-w-5 text-warning [&_svg]:size-3.5" onClick={() => setOpen(true)} />
    <Modal open={open} onClose={() => setOpen(false)} title={materia} className="w-[270px]">
      <ul className="flex max-h-64 flex-col gap-1.5 overflow-auto text-meta">
        {items.map(item => <li key={`${item.date}:${item.key}`}>
          <Link className="flex justify-between gap-3 rounded px-1 py-1 hover:bg-muted" to={`/calendario?data=${item.date}&evento=${encodeURIComponent(item.key)}`} onClick={() => setOpen(false)}>
            <span>{item.day_name} {item.day_number}/{item.month_number}</span><span className="font-mono text-muted-foreground">{item.start_time}–{item.end_time}</span>
          </Link>
        </li>)}
      </ul>
    </Modal>
  </>
}
