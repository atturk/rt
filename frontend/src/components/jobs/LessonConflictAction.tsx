import { lazy, Suspense, useState } from 'react'
import { PencilLine } from 'lucide-react'
import { IconButton } from '@/components/ui/icon-button'
import { hasLessonConflict, type Job } from '@/lib/jobs'

const NewLessonDialog = lazy(() => import('@/components/lessons/NewLessonDialog').then(m => ({ default: m.NewLessonDialog })))

export function LessonConflictAction({ job }: { job: Job }) {
  const [open, setOpen] = useState(false)
  if (job.state !== 'failed' || !hasLessonConflict(job)) return null
  return <>
    <IconButton label="Cambia i dati" icon={PencilLine} onClick={() => setOpen(true)} />
    {open && <Suspense fallback={null}><NewLessonDialog open onClose={() => setOpen(false)} initialJob={job} /></Suspense>}
  </>
}
